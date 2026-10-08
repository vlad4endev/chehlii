"""Оплата: генерация ссылки (для бота), вебхуки шлюзов, страницы Success/Fail.

POST /payments/link отдаёт по ссылке на каждый настроенный шлюз (robokassa, yandex_pay) —
клиент выбирает способ кнопкой в боте; `payment.provider` задаёт лишь порядок. Модель
платежей двухступенчатая: предоплата (% от цены со скидкой) и постоплата (остаток).

Подтверждение оплаты: Robokassa — вебхук с подписью (Пароль №2); Яндекс Пэй — вебхук
без проверки подписи, статус перечитывается по API (см. services/yandex_pay.py).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.internal import require_internal
from app.core.config import settings
from app.core.database import get_session
from app.enums import OrderStatus, PaymentKind, PaymentStatus
from app.models.client import Client
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.services import integrations, robokassa, stock, yandex_pay
from app.services.order_state_machine import can_transition
from app.services.order_status_notify import continue_after_paid, payment_amount

logger = logging.getLogger(__name__)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Статус заказа при успешной оплате данного вида.
_PAID_STATUS = {
    PaymentKind.PREPAYMENT: OrderStatus.PREPAYMENT_PAID,
    PaymentKind.POSTPAYMENT: OrderStatus.POSTPAYMENT_PAID,
}
# Если заказ уже ушёл дальше по воронке, поздний вебхук оплаты не откатывает статус.
_PAST_PREPAY = {
    OrderStatus.HANDED_TO_DESIGN,
    OrderStatus.DESIGN_IN_PROGRESS,
    OrderStatus.MOCKUP_SENT,
    OrderStatus.MOCKUP_APPROVAL,
    OrderStatus.MOCKUP_REVISION,
    OrderStatus.POSTPAYMENT_ISSUED,
    OrderStatus.POSTPAYMENT_PAID,
    OrderStatus.DELIVERY_SERVICE_SELECTION,
    OrderStatus.DELIVERY_ADDRESS_SELECTION,
    OrderStatus.DELIVERY_PAYMENT,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.REVIEW_OFFERED,
    OrderStatus.REVIEW_RECEIVED,
}
_PAST_POSTPAY = {
    OrderStatus.DELIVERY_SERVICE_SELECTION,
    OrderStatus.DELIVERY_ADDRESS_SELECTION,
    OrderStatus.DELIVERY_PAYMENT,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.REVIEW_OFFERED,
    OrderStatus.REVIEW_RECEIVED,
}

_KIND_RU = {"prepayment": "предоплата", "postpayment": "постоплата", "delivery": "доставка"}

class LinkIn(BaseModel):
    order_id: int
    kind: PaymentKind = PaymentKind.PREPAYMENT


class PayOption(BaseModel):
    """Один способ оплаты = одна кнопка в боте и своя строка в payments."""

    provider: str
    url: str
    inv_id: int


class LinkOut(BaseModel):
    amount: float
    # Доля предоплаты — боту, чтобы подписать блок («Предоплата 50%») без похода в настройки.
    percent: float = 0
    # Все настроенные шлюзы; первым — выбранный в `payment.provider`.
    options: list[PayOption]
    # Первая ссылка — для старых ботов, которые ещё читают `url`, а не `options`.
    url: str = ""
    inv_id: int = 0


def _amount(order: Order, kind: PaymentKind, percent: float) -> float:
    return payment_amount(order, kind, percent)


async def robokassa_cfg(session: AsyncSession) -> dict:
    """Креды Robokassa из настроек. Публичная — админка использует её для проверки связи."""
    login = await integrations.get(session, "payment.robokassa_login")
    pass1 = await integrations.get(session, "payment.robokassa_pass1")
    pass2 = await integrations.get(session, "payment.robokassa_pass2")
    if not (login and pass1 and pass2):
        raise HTTPException(400, "Robokassa не настроена — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "payment.robokassa_test", "true") or "true").lower()
    percent = float(await integrations.get(session, "payment.prepay_percent", "50") or 50)
    return {
        "login": login,
        "pass1": pass1,
        "pass2": pass2,
        "is_test": test in ("1", "true", "yes", "да"),
        "percent": percent,
    }


async def yandexpay_cfg(session: AsyncSession) -> dict:
    """Креды Пэй из настроек. Публичная — админка использует её для проверки связи."""
    key = await integrations.get(session, "payment.yandexpay_api_key")
    if not key:
        raise HTTPException(400, "Яндекс Пэй не настроен — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "payment.yandexpay_test", "true") or "true").lower()
    return {
        "api_key": key,
        "merchant_id": await integrations.get(session, "payment.yandexpay_merchant_id"),
        "is_test": test in ("1", "true", "yes", "да"),
        "public_base_url": await integrations.get(session, "payment.yandexpay_public_base_url"),
    }


# Все поддерживаемые шлюзы: клиент видит кнопку на каждый настроенный.
PROVIDERS = ("robokassa", "yandex_pay")


async def _provider(session: AsyncSession) -> str:
    return (await integrations.get(session, "payment.provider", "robokassa") or "robokassa").strip()


async def _yandexpay_link(session: AsyncSession, payment: Payment, description: str) -> str:
    cfg = await yandexpay_cfg(session)
    body = yandex_pay.build_order(
        order_id=str(payment.id),
        amount=float(payment.amount),
        title=description,
        # Ссылка должна жить не меньше, чем заказ до автоотмены, иначе клиент
        # получит напоминание об оплате с уже мёртвой ссылкой.
        ttl_seconds=settings.order_autocancel_hours * 3600,
        redirect_base=cfg["public_base_url"],
    )
    try:
        return await yandex_pay.create_order(cfg, body)
    except yandex_pay.YandexPayError as e:
        raise HTTPException(502, f"Яндекс Пэй: {e}") from e


async def _public_origin(session: AsyncSession) -> str:
    """Публичный адрес сайта, чтобы Success/Fail вели на backend, а не в t.me."""
    for key in ("payment.yandexpay_public_base_url", "ycp.public_base_url"):
        raw = await integrations.get(session, key)
        if raw and raw.strip():
            return raw.strip().rstrip("/")
    return ""


async def _robokassa_link(
    session: AsyncSession, payment: Payment, order: Order, description: str
) -> str:
    cfg = await robokassa_cfg(session)
    origin = await _public_origin(session)
    success = f"{origin}/api/v1/payments/robokassa/success/{payment.id}" if origin else None
    fail = f"{origin}/api/v1/payments/robokassa/fail/{payment.id}" if origin else None
    return robokassa.payment_url(
        login=cfg["login"],
        password1=cfg["pass1"],
        out_sum=float(payment.amount),
        inv_id=payment.id,
        description=description,
        is_test=cfg["is_test"],
        shp={"Shp_order": str(order.id)},
        success_url=success,
        fail_url=fail,
    )


@router.post("/link", response_model=LinkOut, dependencies=[Depends(require_internal)])
async def create_link(body: LinkIn, session: Session) -> LinkOut:
    """Ссылки оплаты для заказа (вызывает бот) — по одной на каждый настроенный шлюз.

    Клиент выбирает способ сам, поэтому создаём свою строку `payments` под каждый:
    у Robokassa и Пэй свои идентификаторы платежа, общей строкой их не развести.
    Ненастроенный (или не ответивший) шлюз просто выпадает из списка.
    `payment.provider` больше не единственный шлюз, а лишь тот, что показываем первым.
    """
    order = await session.get(Order, body.order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    percent = float(await integrations.get(session, "payment.prepay_percent", "50") or 50)
    amount = _amount(order, body.kind, percent)
    if amount <= 0:
        raise HTTPException(400, "Сумма оплаты равна нулю")
    # Ссылка постоплаты после макета / стандарта — статус «выставлена», иначе
    # админка и вебхук видят ещё «согласование макета», хотя клиент уже платит.
    if body.kind == PaymentKind.POSTPAYMENT and can_transition(
        order.status, OrderStatus.POSTPAYMENT_ISSUED
    ):
        order.status = OrderStatus.POSTPAYMENT_ISSUED
        session.add(
            OrderStatusHistory(
                order_id=order.id,
                status=OrderStatus.POSTPAYMENT_ISSUED,
                changed_by="system",
                trigger="Ссылка постоплаты",
                created_at=datetime.now(UTC),
            )
        )

    default = await _provider(session)
    description = f"casetop заказ #{order.id} ({_KIND_RU.get(body.kind, body.kind)})"
    options: list[PayOption] = []
    errors: list[str] = []
    for provider in sorted(PROVIDERS, key=lambda p: p != default):
        payment = Payment(
            order_id=order.id,
            kind=body.kind,
            gateway=provider,
            amount=amount,
            status=PaymentStatus.PENDING,
        )
        session.add(payment)
        await session.flush()  # нужен payment.id: он же InvId у Robokassa и orderId у Пэй
        try:
            if provider == "yandex_pay":
                url = await _yandexpay_link(session, payment, description)
            else:
                url = await _robokassa_link(session, payment, order, description)
        except HTTPException as e:
            # Шлюз не настроен или не ответил — строку не держим, чтобы в оплатах
            # не копились «висяки» без ссылки.
            await session.delete(payment)
            errors.append(f"{provider}: {e.detail}")
            continue
        payment.payment_url = url
        options.append(PayOption(provider=provider, url=url, inv_id=payment.id))

    if not options:
        await session.rollback()
        raise HTTPException(400, " ".join(errors) or "Платёжные шлюзы не настроены")
    await session.commit()
    first = options[0]
    return LinkOut(
        amount=amount,
        percent=percent,
        options=options,
        url=first.url,
        inv_id=first.inv_id,
    )


async def _params(request: Request) -> dict[str, str]:
    data = dict(request.query_params)
    if request.method == "POST":
        data.update({k: str(v) for k, v in (await request.form()).items()})
    return data


def _id_from_params(params: dict[str, str]) -> int | None:
    lowered = {k.lower(): v for k, v in params.items()}
    for key in ("invid", "invoiceid", "orderid"):
        raw = lowered.get(key)
        if raw and str(raw).isdigit():
            return int(raw)
    return None


async def _load_payment(
    session: AsyncSession, params: dict[str, str], payment_id: int | None = None
) -> Payment | None:
    pid = payment_id or _id_from_params(params)
    if pid is None:
        return None
    return await session.get(Payment, pid)


async def _robokassa_proof(
    session: AsyncSession, payment: Payment, params: dict[str, str]
) -> str | None:
    """Чем подтверждена оплата: pass2 (ResultURL), pass1 (SuccessURL), opstate, paid.

    pass2 на странице Success тоже принимаем: в подсказке интеграции ResultURL
    раньше указывали на /success, и подпись паролем №2 там отвергалась.
    """
    if payment.gateway != "robokassa":
        return None
    try:
        cfg = await robokassa_cfg(session)
    except HTTPException:
        return None
    inv_id = str(payment.id)
    out_sum = params.get("OutSum") or params.get("out_summ") or ""
    signature = params.get("SignatureValue") or params.get("Signature") or ""
    shp = robokassa.shp_from(params)
    if robokassa.signature_matches(
        password=cfg["pass2"], out_sum=out_sum, inv_id=inv_id, signature=signature, shp=shp
    ):
        return "pass2"
    if robokassa.signature_matches(
        password=cfg["pass1"], out_sum=out_sum, inv_id=inv_id, signature=signature, shp=shp
    ):
        return "pass1"
    if payment.status == PaymentStatus.PAID:
        return "paid"
    paid = await robokassa.invoice_is_paid(
        login=cfg["login"], password2=cfg["pass2"], inv_id=payment.id
    )
    if paid:
        return "opstate"
    if paid is False:
        logger.info("robokassa: счёт %s не оплачен (подпись и OpStateExt)", payment.id)
    return None


async def _robokassa_result(request: Request, session: AsyncSession):
    """ResultURL: подтверждение оплаты. Ответ «OK<InvId>», иначе Robokassa повторяет запрос."""
    p = await _params(request)
    payment = await _load_payment(session, p)
    if payment is None or payment.gateway != "robokassa":
        return PlainTextResponse("bad invoice", status_code=400)
    proof = await _robokassa_proof(session, payment, p)
    if proof is None:
        return PlainTextResponse("bad sign", status_code=400)
    if proof != "paid":
        payment.raw_webhook = p
        await _apply_paid(session, payment)
    return PlainTextResponse(f"OK{payment.id}")


# Robokassa дёргает ResultURL и GET, и POST. Два обработчика вместо одного
# api_route(methods=[...]): у роута на два метода один operation_id на обе
# операции, из-за чего OpenAPI отдаёт дубликат и ломает генерацию клиентов.
@router.get("/robokassa/result")
async def robokassa_result_get(request: Request, session: Session):
    return await _robokassa_result(request, session)


@router.post("/robokassa/result")
async def robokassa_result_post(request: Request, session: Session):
    return await _robokassa_result(request, session)


@router.post("/yandex-pay/webhook")
async def yandex_pay_webhook(request: Request, session: Session):
    """Callback Яндекс Пэй: тело — JWT (ES256).

    Подпись не проверяем: из payload берём только `orderId`, а платёжный статус
    перечитываем авторизованным запросом к API — подделанный вебхук стоит лишний
    GET, но не ложную оплату. Любой ответ кроме 200 Пэй ретраит до 24 часов.
    """
    try:
        payload = yandex_pay.webhook_payload(await request.body())
    except yandex_pay.YandexPayError as e:
        return JSONResponse(
            {"status": "fail", "reasonCode": "OTHER", "reason": str(e)[:200]}, status_code=400
        )

    order_id = str((payload.get("order") or {}).get("orderId") or "")
    payment = await session.get(Payment, int(order_id)) if order_id.isdigit() else None
    if payment is None or payment.gateway != "yandex_pay":
        return JSONResponse(
            {"status": "fail", "reasonCode": "ORDER_NOT_FOUND", "reason": "unknown order"},
            status_code=404,
        )

    cfg = await yandexpay_cfg(session)
    try:
        status = await yandex_pay.order_status(cfg, order_id)
        # AUTHORIZED — деньги захолдированы; без capture холд снимется и оплаты не будет.
        if status == "AUTHORIZED":
            if await yandex_pay.capture(cfg, order_id, float(payment.amount)) == "SUCCESS":
                status = "CAPTURED"
    except yandex_pay.YandexPayError as e:
        return JSONResponse(
            {"status": "fail", "reasonCode": "OTHER", "reason": str(e)[:200]}, status_code=502
        )

    if status in yandex_pay.PAID_STATUSES:
        payment.raw_webhook = payload
        await _apply_paid(session, payment)
    elif status in yandex_pay.FAILED_STATUSES and payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.FAILED
        payment.raw_webhook = payload
        await session.commit()
    return {"status": "success"}


def _history(order_id: int, status: OrderStatus, trigger: str) -> OrderStatusHistory:
    return OrderStatusHistory(
        order_id=order_id,
        status=status,
        changed_by="system",
        trigger=trigger,
        created_at=datetime.now(UTC),
    )


async def _apply_paid(session: AsyncSession, payment: Payment) -> None:
    """Провести оплату: статус заказа, списание остатков, следующий шаг сценария.

    Идемпотентно — вебхуки шлюзов повторяются, второй раз ничего не меняем.
    """
    now = datetime.now(UTC)
    claimed = await session.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status != PaymentStatus.PAID)
        .values(status=PaymentStatus.PAID, paid_at=now)
    )
    if claimed.rowcount == 0:
        await session.commit()
        return
    payment.status = PaymentStatus.PAID
    payment.paid_at = now
    # На заказ выставлено по счёту на каждый шлюз — оставшиеся закрываем, иначе в
    # оплатах висят дубли на ту же сумму и клиент может заплатить дважды.
    await session.execute(
        update(Payment)
        .where(
            Payment.order_id == payment.order_id,
            Payment.kind == payment.kind,
            Payment.id != payment.id,
            Payment.status == PaymentStatus.PENDING,
        )
        .values(status=PaymentStatus.CANCELLED)
    )
    order = await session.get(Order, payment.order_id)
    if order is not None:
        order.payment_status = PaymentStatus.PAID
        new = _PAID_STATUS.get(payment.kind)
        rewind = (new == OrderStatus.PREPAYMENT_PAID and order.status in _PAST_PREPAY) or (
            new == OrderStatus.POSTPAYMENT_PAID and order.status in _PAST_POSTPAY
        )
        if new is not None and not rewind:
            order.status = new
            if new == OrderStatus.PREPAYMENT_PAID:
                await stock.deduct_for_order(session, order)
            session.add(_history(order.id, new, f"{payment.gateway}: оплата подтверждена"))
        client = await session.get(Client, order.client_id)
        # Заказ уже дальше по воронке — повторный вебхук не шлёт шаг заново.
        if not rewind:
            await continue_after_paid(session, order, client, kind=payment.kind)
    await session.commit()


_PAGE = """<!doctype html><html lang=ru><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>casetop</title>
<style>body{{font-family:system-ui,sans-serif;background:#f4f4f3;color:#17181a;display:grid;
place-items:center;min-height:100vh;margin:0}}.c{{text-align:center;max-width:340px;padding:28px}}
h1{{font-size:22px;margin:0 0 10px}}p{{color:#6d6f73;line-height:1.5;margin:0 0 18px}}
a.btn{{display:inline-block;padding:12px 18px;border-radius:12px;background:#17181a;color:#fff;
text-decoration:none;font-weight:600}}</style>
<div class=c><h1>{title}</h1><p>{text}</p>{button}</div>"""


def _bot_return_button(channel: str | None, payment_id: int | None) -> str:
    """Кнопка возврата в свой бот. start=pay_<id> заставляет бота сверить оплату и продолжить."""
    payload = f"pay_{payment_id}" if payment_id else ""
    if channel == "max":
        url = f"https://max.ru/{settings.max_bot_username}"
        label = "Открыть MAX-бот"
    else:
        url = f"https://t.me/{settings.tg_bot_username}"
        label = "Открыть Telegram-бот"
    if payload:
        url = f"{url}?start={payload}"
    return f'<a class="btn" href="{url}">{label}</a>'


async def _client_channel_from_params(
    session: AsyncSession, params: dict[str, str], payment_id: int | None = None
) -> str | None:
    """Канал клиента по InvId платежа или Shp_order — чтобы SuccessURL не слал всех в t.me."""
    order_id: int | None = None
    shp = robokassa.shp_from(params)
    shp_order = shp.get("Shp_order") or shp.get("shp_order")
    if shp_order and str(shp_order).isdigit():
        order_id = int(shp_order)
    if order_id is None:
        payment = await _load_payment(session, params, payment_id)
        if payment is not None:
            order_id = payment.order_id
    if order_id is None:
        return None
    order = await session.get(Order, order_id)
    if order is None:
        return None
    client = await session.get(Client, order.client_id)
    return client.channel if client else None


async def _try_apply_from_redirect(
    session: AsyncSession, params: dict[str, str], payment_id: int | None = None
) -> str | None:
    """SuccessURL и возврат в бота — запасной вход, если ResultURL не дошёл.

    Возвращает способ подтверждения Robokassa (pass2 → ответ OK, не HTML).
    """
    payment = await _load_payment(session, params, payment_id)
    if payment is None or payment.status == PaymentStatus.PAID:
        if payment is not None and payment.gateway == "robokassa":
            return await _robokassa_proof(session, payment, params)
        return None
    if payment.gateway == "robokassa":
        proof = await _robokassa_proof(session, payment, params)
        if proof in ("pass1", "pass2", "opstate"):
            payment.raw_webhook = params or {"InvId": str(payment.id), "source": proof}
            await _apply_paid(session, payment)
        return proof
    if payment.gateway != "yandex_pay":
        return None
    try:
        cfg = await yandexpay_cfg(session)
        status = await yandex_pay.order_status(cfg, str(payment.id))
        if status == "AUTHORIZED":
            if await yandex_pay.capture(cfg, str(payment.id), float(payment.amount)) == "SUCCESS":
                status = "CAPTURED"
        if status in yandex_pay.PAID_STATUSES:
            payment.raw_webhook = params
            await _apply_paid(session, payment)
    except (HTTPException, yandex_pay.YandexPayError):
        return None
    return None


async def _success_response(
    request: Request, session: AsyncSession, payment_id: int | None = None
) -> HTMLResponse:
    params = await _params(request)
    await _try_apply_from_redirect(session, params, payment_id)
    pid = payment_id or _id_from_params(params)
    channel = await _client_channel_from_params(session, params, pid)
    page = _PAGE.format(
        title="Оплата прошла ✅",
        text="Спасибо! Вернитесь в чат бота — продолжим оформление.",
        button=_bot_return_button(channel, pid),
    )
    return HTMLResponse(page)


@router.get("/success")
@router.get("/robokassa/success")
async def payment_success_get(request: Request, session: Session) -> HTMLResponse:
    return await _success_response(request, session)


@router.post("/success")
@router.post("/robokassa/success")
async def payment_success_post(request: Request, session: Session) -> HTMLResponse:
    return await _success_response(request, session)


@router.get("/robokassa/success/{payment_id}")
async def payment_success_id_get(
    payment_id: int, request: Request, session: Session
) -> HTMLResponse:
    return await _success_response(request, session, payment_id)


@router.post("/robokassa/success/{payment_id}")
async def payment_success_id_post(
    payment_id: int, request: Request, session: Session
) -> HTMLResponse:
    return await _success_response(request, session, payment_id)


async def _fail_page(
    request: Request, session: AsyncSession, payment_id: int | None = None
) -> str:
    params = await _params(request)
    pid = payment_id or _id_from_params(params)
    channel = await _client_channel_from_params(session, params, pid)
    return _PAGE.format(
        title="Оплата не завершена",
        text="Платёж отменён или не прошёл. Вернитесь в бот и попробуйте снова.",
        button=_bot_return_button(channel, None),
    )


@router.get("/fail", response_class=HTMLResponse)
@router.get("/robokassa/fail", response_class=HTMLResponse)
async def payment_fail_get(request: Request, session: Session) -> str:
    return await _fail_page(request, session)


@router.post("/fail", response_class=HTMLResponse)
@router.post("/robokassa/fail", response_class=HTMLResponse)
async def payment_fail_post(request: Request, session: Session) -> str:
    return await _fail_page(request, session)


@router.get("/robokassa/fail/{payment_id}", response_class=HTMLResponse)
async def payment_fail_id_get(payment_id: int, request: Request, session: Session) -> str:
    return await _fail_page(request, session, payment_id)


@router.post("/robokassa/fail/{payment_id}", response_class=HTMLResponse)
async def payment_fail_id_post(payment_id: int, request: Request, session: Session) -> str:
    return await _fail_page(request, session, payment_id)


@router.post("/{payment_id}/sync", dependencies=[Depends(require_internal)])
async def sync_payment(payment_id: int, session: Session) -> dict:
    """Бот после возврата из Robokassa: сверить счёт и, если оплачен, продолжить сценарий."""
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Платёж не найден")
    if payment.status != PaymentStatus.PAID:
        await _try_apply_from_redirect(
            session, {"InvId": str(payment.id), "orderId": str(payment.id)}, payment.id
        )
        await session.refresh(payment)
    return {
        "status": payment.status,
        "order_id": payment.order_id,
        "kind": payment.kind,
    }
