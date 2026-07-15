"""Robokassa: формирование ссылки оплаты и проверка подписи вебхука.

Ссылка оплаты: подпись MD5(MerchantLogin:OutSum:InvId:Пароль1[:Shp_*]).
ResultURL (вебхук): подпись MD5(OutSum:InvId:Пароль2[:Shp_*]), ответ «OK<InvId>».
SuccessURL: подпись MD5(OutSum:InvId:Пароль1[:Shp_*]).
Док: https://docs.robokassa.ru/ru/pay-interface
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlencode

PAYMENT_BASE = "https://auth.robokassa.ru/Merchant/Index.aspx"


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
