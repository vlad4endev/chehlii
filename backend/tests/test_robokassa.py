"""Тесты пробы связи с Robokassa. Сеть не трогаем — только разбор OpStateExt."""

from app.services import robokassa as rk

XML_NS = (
    '<OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">'
    "<Result><Code>{code}</Code></Result>"
    "</OperationStateResponse>"
)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _fake_get(text: str, status_code: int, monkeypatch, seen: list):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            seen.append((url, kw.get("params") or {}))
            return _FakeResponse(status_code, text)

    monkeypatch.setattr(rk.httpx, "AsyncClient", Client)


def test_op_state_parses_result_code_not_state_code():
    xml = (
        "<OperationStateResponse><Result><Code>3</Code></Result>"
        "<State><Code>100</Code></State></OperationStateResponse>"
    )
    assert rk.op_state_result_code(xml) == 3


def test_op_state_garbage_is_none():
    assert rk.op_state_result_code("not xml") is None
    assert rk.op_state_result_code("") is None


async def test_unknown_invoice_means_creds_ok(monkeypatch):
    seen: list = []
    _fake_get(XML_NS.format(code=3), 200, monkeypatch, seen)
    ok, detail = await rk.check_connection(login="shop", password2="p2", is_test=True)
    assert ok is True
    assert "пароль №2 приняты" in detail
    assert "тест" in detail
    url, params = seen[0]
    assert url == rk.OP_STATE_URL
    assert params["InvoiceID"] == str(rk.PROBE_INVOICE_ID)
    assert params["MerchantLogin"] == "shop"
    assert params["Signature"] == rk._md5(f"shop:{rk.PROBE_INVOICE_ID}:p2")


async def test_bad_password2(monkeypatch):
    _fake_get(XML_NS.format(code=1), 200, monkeypatch, [])
    ok, detail = await rk.check_connection(login="shop", password2="wrong", is_test=False)
    assert ok is False
    assert "пароль №2 отклонён" in detail
    assert "продакшен" in detail


async def test_unknown_shop(monkeypatch):
    _fake_get(XML_NS.format(code=2), 200, monkeypatch, [])
    ok, detail = await rk.check_connection(login="no-such", password2="p2", is_test=True)
    assert ok is False
    assert "магазин не найден" in detail


async def test_empty_creds_skip_network(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("без кредов сеть трогать нельзя")

    monkeypatch.setattr(rk.httpx, "AsyncClient", boom)
    ok, detail = await rk.check_connection(login="", password2="p2", is_test=True)
    assert ok is False
    assert "не заданы" in detail
