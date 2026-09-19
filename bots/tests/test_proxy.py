"""URL сессии бота для SOCKS/HTTP-ключей — без запуска xray."""

"""URL сессии бота для SOCKS/HTTP-ключей — без запуска xray."""

import pytest

from bots.tg.proxy import ProxyError, session_url_for


def test_session_url_vless_uses_local_socks():
    url = session_url_for({"kind": "vless", "socks_url": "socks5://127.0.0.1:10808"})
    assert url == "socks5://127.0.0.1:10808"


def test_session_url_socks_passthrough():
    url = session_url_for({"kind": "socks", "proxy_url": "socks5://user:pass@10.0.0.1:1080"})
    assert url.startswith("socks5://")


def test_session_url_missing_raises():
    with pytest.raises(ProxyError):
        session_url_for({"kind": "socks"})
