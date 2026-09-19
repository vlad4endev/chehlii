"""Разбор VLESS/SOCKS-ссылок и сборка конфига xray. Сеть не трогаем."""

from app.services.tg_proxy_parse import (
    ProxyParseError,
    add_uris,
    candidate,
    extract_uris,
    fingerprint,
    parse_share_link,
    public_key,
    xray_config,
)

REALITY = (
    "vless://11111111-1111-1111-1111-111111111111@nl.example.com:443"
    "?type=tcp&encryption=none&security=reality&pbk=PUBKEY"
    "&fp=chrome&sni=www.microsoft.com&sid=abcd&spx=%2F&flow=xtls-rprx-vision"
    "#NL-1"
)

WS_TLS = (
    "vless://22222222-2222-2222-2222-222222222222@ws.example.com:443"
    "?type=ws&security=tls&path=%2Fray&host=ws.example.com&sni=ws.example.com"
    "&fp=chrome&alpn=http%2F1.1#CDN"
)

SOCKS = "socks5://user:p%40ss@10.0.0.9:1080#backup"


def test_parse_vless_reality_vision():
    info = parse_share_link(REALITY)
    assert info["kind"] == "vless"
    assert info["host"] == "nl.example.com"
    assert info["port"] == 443
    assert info["network"] == "tcp"
    assert info["security"] == "reality"
    assert info["label"] == "NL-1"
    user = info["xray_outbound"]["settings"]["vnext"][0]["users"][0]
    assert user["id"] == "11111111-1111-1111-1111-111111111111"
    assert user["flow"] == "xtls-rprx-vision"
    reality = info["xray_outbound"]["streamSettings"]["realitySettings"]
    assert reality["publicKey"] == "PUBKEY"
    assert reality["serverName"] == "www.microsoft.com"
    assert reality["shortId"] == "abcd"
    assert reality["spiderX"] == "/"


def test_parse_vless_ws_tls_drops_flow():
    uri = WS_TLS.replace("#CDN", "&flow=xtls-rprx-vision#CDN")
    info = parse_share_link(uri)
    user = info["xray_outbound"]["settings"]["vnext"][0]["users"][0]
    assert "flow" not in user
    stream = info["xray_outbound"]["streamSettings"]
    assert stream["network"] == "ws"
    assert stream["security"] == "tls"
    assert stream["wsSettings"]["path"] == "/ray"
    assert stream["tlsSettings"]["alpn"] == ["http/1.1"]


def test_parse_socks5_keeps_password():
    info = parse_share_link(SOCKS)
    assert info["kind"] == "socks"
    assert info["host"] == "10.0.0.9"
    assert info["port"] == 1080
    assert info["proxy_url"] == "socks5://user:p%40ss@10.0.0.9:1080"
    assert info["xray_outbound"] is None
    assert info["label"] == "backup"


def test_parse_grpc_and_httpupgrade():
    grpc = (
        "vless://33333333-3333-3333-3333-333333333333@g.example.com:443"
        "?type=grpc&security=tls&serviceName=Tun&mode=gun&sni=g.example.com#gRPC"
    )
    info = parse_share_link(grpc)
    assert info["network"] == "grpc"
    assert info["xray_outbound"]["streamSettings"]["grpcSettings"]["serviceName"] == "Tun"

    up = (
        "vless://44444444-4444-4444-4444-444444444444@h.example.com:443"
        "?type=httpupgrade&security=tls&path=%2Fup&host=h.example.com#up"
    )
    info2 = parse_share_link(up)
    assert info2["network"] == "httpupgrade"
    assert info2["xray_outbound"]["streamSettings"]["httpupgradeSettings"]["path"] == "/up"


def test_reject_vmess_and_empty():
    try:
        parse_share_link("vmess://abcd")
        raise AssertionError("expected ProxyParseError")
    except ProxyParseError as e:
        assert "VMess" in str(e)
    try:
        parse_share_link("  ")
        raise AssertionError("expected ProxyParseError")
    except ProxyParseError as e:
        assert "Пустая" in str(e)
    try:
        parse_share_link(
            "vless://11111111-1111-1111-1111-111111111111@h.example:443?type=tcp&security=reality"
        )
        raise AssertionError("expected ProxyParseError")
    except ProxyParseError as e:
        assert "pbk" in str(e)


def test_extract_from_subscription_blob():
    blob = f"# comment\n{REALITY}\n\n{SOCKS}\nnot-a-link\n"
    uris = extract_uris(blob)
    assert REALITY in uris
    assert SOCKS in uris
    assert all(u.startswith(("vless://", "socks5://")) for u in uris)


def test_xray_config_routes_socks_to_vless():
    info = parse_share_link(REALITY)
    cfg = xray_config(info["xray_outbound"], socks_port=10808)
    assert cfg["inbounds"][0]["port"] == 10808
    assert cfg["inbounds"][0]["listen"] == "127.0.0.1"
    assert cfg["outbounds"][0]["protocol"] == "vless"
    assert cfg["outbounds"][0]["tag"] == "proxy"
    assert cfg["routing"]["rules"][0]["outboundTag"] == "proxy"
    dumped = str(cfg)
    assert "11111111-1111-1111-1111-111111111111" in dumped


def test_public_key_hides_uri_and_uuid():
    stored = {"id": "abc", "uri": REALITY, "enabled": True, "label": "NL-1", "added_at": "t"}
    pub = public_key(stored)
    assert "uri" not in pub
    assert "11111111" not in str(pub)
    assert pub["kind"] == "vless"
    assert pub["host"] == "nl.example.com"
    assert pub["security"] == "reality"


def test_candidate_vless_has_local_socks():
    stored = {"id": "abc", "uri": REALITY, "enabled": True, "label": "NL-1"}
    item = candidate(stored)
    assert item is not None
    assert item["socks_url"] == "socks5://127.0.0.1:10808"
    assert item["xray_config"]["outbounds"][0]["protocol"] == "vless"
    disabled = candidate({**stored, "enabled": False})
    assert disabled is None


def test_add_uris_skips_duplicates_and_fingerprint_changes():
    keys, added = add_uris([], REALITY)
    assert added == ["NL-1"]
    fp1 = fingerprint(True, keys)
    try:
        add_uris(keys, REALITY)
        raise AssertionError("expected duplicate error")
    except ProxyParseError as e:
        assert "уже сохранены" in str(e)
    keys2, added2 = add_uris(keys, SOCKS)
    assert added2 == ["backup"]
    fp2 = fingerprint(True, keys2)
    assert fp1 != fp2
    assert fingerprint(False, keys2) != fp2


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(_name, "ok")
    print("all ok")
