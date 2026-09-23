"""Robokassa: формирование ссылки оплаты и проверка подписи вебхука.

Ссылка оплаты: подпись MD5(MerchantLogin:OutSum:InvId:Пароль1[:Shp_*]).
ResultURL (вебхук): подпись MD5(OutSum:InvId:Пароль2[:Shp_*]), ответ «OK<InvId>».
SuccessURL: подпись MD5(OutSum:InvId:Пароль1[:Shp_*]).
Проба связи — OpStateExt по заведомо чужому InvoiceID: платежей не создаёт,
проверяет MerchantLogin и Пароль №2 (им подписывается вебхук).
Док: https://docs.robokassa.ru/ru/pay-interface
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlencode

import httpx

PAYMENT_BASE = "https://auth.robokassa.ru/Merchant/Index.aspx"
OP_STATE_URL = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt"
# InvoiceID в OpStateExt должен быть > 0. Единица заведомо не наш платёж —
# код 3 «не найдено» как раз и значит, что логин и пароль №2 приняты.
PROBE_INVOICE_ID = 1
# Первый <Code> внутри <Result> — итог запроса, не статус операции.
_RESULT_CODE = re.compile(r"<Result>\s*<Code>(-?\d+)</Code>", re.IGNORECASE)


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _shp_tail(shp: dict[str, str] | None) -> str:
    """Пользовательские Shp_-параметры в подпись: сортированные :Shp_key=value."""
    if not shp:
        return ""
    return "".join(f":{k}={shp[k]}" for k in sorted(shp))


def payment_url(
    *,
    login: str,
    password1: str,
    out_sum: float,
    inv_id: int,
    description: str,
    is_test: bool = False,
    shp: dict[str, str] | None = None,
) -> str:
    out = f"{out_sum:.2f}"
    signature = _md5(f"{login}:{out}:{inv_id}:{password1}{_shp_tail(shp)}")
    params: dict[str, str] = {
        "MerchantLogin": login,
        "OutSum": out,
        "InvId": str(inv_id),
        "Description": description[:100],
        "SignatureValue": signature,
        "Culture": "ru",
        "Encoding": "utf-8",
    }
    if is_test:
        params["IsTest"] = "1"
    if shp:
        params.update(shp)
    return f"{PAYMENT_BASE}?{urlencode(params)}"


def verify_result(
    *, password2: str, out_sum: str, inv_id: str, signature: str, shp: dict[str, str] | None = None
) -> bool:
    expected = _md5(f"{out_sum}:{inv_id}:{password2}{_shp_tail(shp)}")
    return expected.lower() == (signature or "").lower()


def verify_success(
    *, password1: str, out_sum: str, inv_id: str, signature: str, shp: dict[str, str] | None = None
) -> bool:
    expected = _md5(f"{out_sum}:{inv_id}:{password1}{_shp_tail(shp)}")
    return expected.lower() == (signature or "").lower()


def op_state_result_code(xml_text: str) -> int | None:
    """Result.Code из XML OpStateExt. Namespace в тегах Robokassa не ставит."""
    m = _RESULT_CODE.search(xml_text or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


async def check_connection(*, login: str, password2: str, is_test: bool) -> tuple[bool, str]:
    """Статус связи с Robokassa без побочных эффектов.

    OpStateExt по InvoiceID=1: 3 (счёт не найден) / 0 / 4 = логин и пароль №2
    приняты; 1 = пароль №2 не тот; 2 = магазин не найден. Пароль №1 этой пробой
    не проверить — он участвует только в ссылке оплаты. Платежей не создаём.
    """
    mode = "тест" if is_test else "продакшен"
    if not login or not password2:
        return False, "не заданы MerchantLogin или Пароль №2"
    signature = _md5(f"{login}:{PROBE_INVOICE_ID}:{password2}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                OP_STATE_URL,
                params={
                    "MerchantLogin": login,
                    "InvoiceID": str(PROBE_INVOICE_ID),
                    "Signature": signature,
                },
            )
    except httpx.HTTPError as e:
        return False, f"нет связи ({mode}): {e}"[:200]
    if r.status_code != 200:
        return False, f"нет связи ({mode}): HTTP {r.status_code} {r.text[:120]}"
    code = op_state_result_code(r.text)
    if code in (0, 3, 4):
        return True, f"связь есть, логин и пароль №2 приняты ({mode})"
    if code == 1:
        return False, f"пароль №2 отклонён ({mode}): неверная подпись"
    if code == 2:
        return False, f"магазин не найден ({mode}): проверьте MerchantLogin"
    if code is None:
        return False, f"нет связи ({mode}): неожиданный ответ Robokassa"
    return False, f"нет связи ({mode}): код {code}"
