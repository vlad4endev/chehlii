"""URL сессии бота для VLESS/Hysteria2/SOCKS — без запуска клиентов."""

import pytest

from bots.tg.proxy import ProxyError, _hysteria_yaml, session_url_for


def test_session_url_vless_uses_local_socks():
    url = session_url_for({"kind": "vless", "socks_url": "socks5://127.0.0.1:10808"})
    assert url == "socks5://127.0.0.1:10808"


def test_session_url_hysteria2_uses_local_socks():
    url = session_url_for({"kind": "hysteria2", "socks_url": "socks5://127.0.0.1:10808"})
    assert url == "socks5://127.0.0.1:10808"


def test_session_url_socks_passthrough():
    url = session_url_for({"kind": "socks", "proxy_url": "socks5://user:pass@10.0.0.1:1080"})
    assert url.startswith("socks5://")


def test_session_url_missing_raises():
    with pytest.raises(ProxyError):
        session_url_for({"kind": "socks"})


def test_hysteria_yaml_quotes_auth():
    text = _hysteria_yaml(
        {
            "server": "nl.example.com:443",
            "auth": "p:ss#word",
            "lazy": True,
            "socks5": {"listen": "127.0.0.1:10808", "disableUDP": True},
        }
    )
    assert "auth: \"p:ss#word\"" in text or 'auth: "p:ss#word"' in text
    assert "lazy: true" in text
    assert "disableUDP: true" in text
    assert "listen: \"127.0.0.1:10808\"" in text or 'listen: "127.0.0.1:10808"' in text
