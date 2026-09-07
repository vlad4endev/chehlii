"""Клиентское оформление доставки: адрес → расчёт → оплата в боте → заявка в API.

Адрес храним в `orders.delivery_address` префиксом, чтобы не плодить колонки:
- `pvz:CODE|человекочитаемо`
- `door:ИНДЕКС|улица дом квартира`

После постоплаты заказ переходит к выбору службы (СДЭК / Яндекс, если обе
настроены). Заявку создаём, когда клиент оплатил доставку.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import DeliveryService, OrderStatus
from app.models.client import Client
from app.models.messaging import OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.services import cdek, pricing
from app.services.order_state_machine import InvalidTransition, assert_transition

# Цепочка статусов от «чехол оплачен» до «ждём оплату доставки».
DELIVERY_CHAIN = [
    OrderStatus.POSTPAYMENT_PAID,
    OrderStatus.DELIVERY_SERVICE_SELECTION,
    OrderStatus.DELIVERY_ADDRESS_SELECTION,
    OrderStatus.DELIVERY_PAYMENT,
]

_TRUE = ("1", "true", "yes", "да")


def encode_destination(
    *,
    pickup_point_id: str | None = None,
    to_postal: str | None = None,
    to_address: str | None = None,
    label: str | None = None,
) -> str:
    """Сериализовать выбранный ПВЗ или адрес двери для поля заказа."""
    if pickup_point_id:
        human = (label or pickup_point_id).strip()
        return f"pvz:{pickup_point_id.strip()}|{human}"
    postal = (to_postal or "").strip()
    address = (to_address or "").strip()
    return f"door:{postal}|{address}"


def decode_destination(stored: str | None) -> dict:
    """Разобрать сохранённый адрес. Неизвестное считаем адресом до двери."""
    raw = (stored or "").strip()
    if raw.startswith("pvz:"):
        rest = raw[4:]
        code, _, human = rest.partition("|")
        code = code.strip()
        return {
            "pickup_point_id": code or None,
            "to_postal": None,
            "to_address": None,
            "label": (human or code).strip(),
        }
    if raw.startswith("door:"):
        rest = raw[5:]
        postal, _, address = rest.partition("|")
        address = address.strip()
        postal = postal.strip()
        return {
            "pickup_point_id": None,
            "to_postal": postal or None,
            "to_address": address or None,
            "label": address or postal,
        }
    if raw.upper().startswith("ПВЗ "):
        code = raw.split(None, 1)[-1].strip()
        return {
            "pickup_point_id": code or None,
            "to_postal": None,
            "to_address": None,
            "label": raw,
        }
    return {
        "pickup_point_id": None,
        "to_postal": None,
        "to_address": raw or None,
        "label": raw,
    }


def statuses_to_apply(current: OrderStatus, target: OrderStatus) -> list[OrderStatus]:
    """Промежуточные статусы по цепочке доставки, не включая текущий."""
    if current == target:
        return []
    if current not in DELIVERY_CHAIN or target not in DELIVERY_CHAIN:
        return [target]
    start = DELIVERY_CHAIN.index(current)
    end = DELIVERY_CHAIN.index(target)
    if end <= start:
        return []
    return list(DELIVERY_CHAIN[start + 1 : end + 1])


async def walk_to(
    session: AsyncSession, order: Order, target: OrderStatus, trigger: str
) -> None:
    """Продвинуть заказ по цепочке доставки, записывая каждый переход."""
    for status in statuses_to_apply(order.status, target):
        assert_transition(order.status, status)
        order.status = status
        session.add(
            OrderStatusHistory(
                order_id=order.id,
                status=status,
                changed_by="system",
                trigger=trigger,
                created_at=datetime.now(UTC),
            )
        )


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


async def load_cfg(session: AsyncSession) -> dict:
    """Креды СДЭК из интеграций. Пустые ключи — CdekError, не HTTPException."""
    from app.services import integrations

    account = cdek.sanitize_secret(await integrations.get(session, "cdek.account"))
    secret = cdek.sanitize_secret(await integrations.get(session, "cdek.secret"))
    if not (account and secret):
        raise cdek.CdekError("СДЭК не настроен — задайте в «Настройки → Интеграции».")
    test = (await integrations.get(session, "cdek.test", "false") or "false").lower()
    return {
        "account": account,
        "secret": secret,
        "is_test": test in _TRUE,
        "from_postal": await integrations.get(session, "cdek.from_postal", "101000"),
        "from_address": await integrations.get(session, "cdek.from_address"),
        "shipment_point": await integrations.get(session, "cdek.shipment_point"),
        "tariff_code": _int(await integrations.get(session, "cdek.tariff_code", "137"), 137),
        "tariff_pickup": _int(await integrations.get(session, "cdek.tariff_pickup", "136"), 136),
        "weight": _int(await integrations.get(session, "cdek.weight", "300"), 300),
        "sender_name": await integrations.get(session, "cdek.sender_name", "casetop"),
        "sender_phone": await integrations.get(session, "cdek.sender_phone"),
    }


async def available_services(session: AsyncSession) -> list[str]:
    """Какие службы реально настроены — бот показывает только их."""
    from app.services import integrations
    from app.services.yandex_delivery import sanitize_token

    out: list[str] = []
    account = cdek.sanitize_secret(await integrations.get(session, "cdek.account"))
    secret = cdek.sanitize_secret(await integrations.get(session, "cdek.secret"))
    if account and secret:
        out.append("cdek")
    if sanitize_token(await integrations.get(session, "yandex.oauth_token")):
        out.append("yandex")
    return out


async def load_yandex_cfg(session: AsyncSession) -> dict:
    from app.services import integrations
    from app.services import yandex_delivery as yd

    token = yd.sanitize_token(await integrations.get(session, "yandex.oauth_token"))
    if not token:
        raise yd.YandexDeliveryError(
            "Яндекс Доставка не настроена — задайте в «Настройки → Интеграции»."
        )
    test = (await integrations.get(session, "yandex.test", "false") or "false").lower()
    return {
        "token": token,
        "is_test": test in _TRUE,
        "merchant_id": await integrations.get(session, "yandex.merchant_id"),
        "platform_station_id": await integrations.get(session, "yandex.platform_station_id"),
        "last_mile_policy": await integrations.get(
            session, "yandex.last_mile_policy", "time_interval"
        ),
        "payment_method": await integrations.get(session, "yandex.payment_method", "already_paid"),
        "weight": _int(await integrations.get(session, "yandex.weight", "300"), 300),
        "pickup_delay_hours": _int(
            await integrations.get(session, "yandex.pickup_delay_hours", "24"), 24
        ),
        "nds": _int(await integrations.get(session, "yandex.nds", "0"), 0),
        "geocoder_apikey": await integrations.get(session, "yandex.geocoder_apikey"),
    }


def _days_until(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((dt.date() - datetime.now(UTC).date()).days, 0)


_QUOTE_STATUSES = {
    OrderStatus.POSTPAYMENT_PAID,
    OrderStatus.DELIVERY_SERVICE_SELECTION,
    OrderStatus.DELIVERY_ADDRESS_SELECTION,
    OrderStatus.DELIVERY_PAYMENT,
}


async def _save_quoted(
    session: AsyncSession,
    order: Order,
    *,
    service: DeliveryService,
    stored: str,
    cost: float,
    chosen_label: str,
) -> None:
    if order.status in {
        OrderStatus.POSTPAYMENT_PAID,
        OrderStatus.DELIVERY_SERVICE_SELECTION,
    }:
        await walk_to(
            session, order, OrderStatus.DELIVERY_ADDRESS_SELECTION, f"Клиент выбрал {chosen_label}"
        )
    await walk_to(session, order, OrderStatus.DELIVERY_PAYMENT, "Клиент подтвердил адрес")
    order.delivery_service = service
    order.delivery_address = stored
    order.delivery_cost = cost


async def resolve_city_code(cfg: dict, query: str) -> int | None:
    """Код города СДЭК по названию или индексу."""
    found = await cdek.cities(cfg, query, size=1)
    if not found:
        return None
    code = found[0].get("code")
    return int(code) if code is not None else None


async def calculate_quote(
    cfg: dict,
    *,
    pickup_point_id: str | None = None,
    to_postal: str | None = None,
    to_city: str | None = None,
    weight_g: int | None = None,
) -> dict:
    """Стоимость и срок: ПВЗ, индекс или название города."""
    to_city_code = None
    if not pickup_point_id and not to_postal and to_city:
        to_city_code = await resolve_city_code(cfg, to_city)
        if to_city_code is None:
            raise cdek.CdekError(f"город «{to_city}» не найден в СДЭК")
    return await cdek.calculate(
        cfg,
        to_postal=to_postal,
        to_city_code=to_city_code,
        delivery_point=pickup_point_id,
        weight_g=weight_g or cfg["weight"],
    )


def _item_price(order: Order) -> float:
    return float(
        pricing.compute(
            order.cost or 0, order.margin or 0, float(order.total_discount or 0)
        ).price_with_discount
    )


def _notify(
    session: AsyncSession, client: Client, order_id: int, text: str, kind: str = "text"
) -> None:
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            order_id=order_id,
            kind=kind,
            text=text,
        )
    )


async def start_after_postpayment(
    session: AsyncSession, order: Order, client: Client | None
) -> None:
    """После оплаты чехла — выбор службы в боте. Идемпотентно.

    Ошибку перехода глотаем: оплата уже прошла, клиент не должен застревать
    без сообщения из-за рассинхрона статусов (макет → постоплата без issued).
    """
    if order.status == OrderStatus.POSTPAYMENT_PAID:
        try:
            await walk_to(
                session,
                order,
                OrderStatus.DELIVERY_SERVICE_SELECTION,
                "Постоплата: переход к доставке",
            )
        except InvalidTransition:
            order.status = OrderStatus.DELIVERY_SERVICE_SELECTION
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    status=OrderStatus.DELIVERY_SERVICE_SELECTION,
                    changed_by="system",
                    trigger="Постоплата: переход к доставке",
                    created_at=datetime.now(UTC),
                )
            )
    elif order.status != OrderStatus.DELIVERY_SERVICE_SELECTION:
        return
    if client is None:
        return
    _notify(
        session,
        client,
        order.id,
        "Оплата прошла ✅ Оформите доставку.",
        kind="delivery",
    )


async def apply_quote(
    session: AsyncSession,
    order: Order,
    *,
    pickup_point_id: str | None = None,
    to_postal: str | None = None,
    to_address: str | None = None,
    to_city: str | None = None,
    label: str | None = None,
) -> dict:
    """Посчитать СДЭК, сохранить адрес и выставить оплату доставки."""
    if order.tracking_code:
        raise cdek.CdekError("заявка СДЭК по этому заказу уже создана")
    if order.status not in _QUOTE_STATUSES:
        raise cdek.CdekError("для этого заказа доставку оформить нельзя")
    if not (pickup_point_id or to_address):
        raise cdek.CdekError("укажите ПВЗ или адрес до двери")

    cfg = await load_cfg(session)
    calc = await calculate_quote(
        cfg,
        pickup_point_id=pickup_point_id,
        to_postal=to_postal,
        to_city=to_city,
    )
    stored = encode_destination(
        pickup_point_id=pickup_point_id,
        to_postal=to_postal,
        to_address=to_address,
        label=label,
    )
    try:
        await _save_quoted(
            session,
            order,
            service=DeliveryService.CDEK,
            stored=stored,
            cost=calc["delivery_sum"],
            chosen_label="СДЭК",
        )
    except InvalidTransition as e:
        raise cdek.CdekError(str(e)) from e
    return {**calc, "address": decode_destination(stored)["label"], "service": "cdek"}


async def apply_yandex_quote(
    session: AsyncSession,
    order: Order,
    *,
    pickup_point_id: str | None = None,
    to_address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    label: str | None = None,
) -> dict:
    """Посчитать Яндекс Доставку, сохранить адрес и выставить оплату."""
    from app.services import yandex_delivery as yd

    if order.tracking_code:
        raise yd.YandexDeliveryError("заявка по этому заказу уже создана")
    if order.status not in _QUOTE_STATUSES:
        raise yd.YandexDeliveryError("для этого заказа доставку оформить нельзя")
    if not (pickup_point_id or to_address):
        raise yd.YandexDeliveryError("укажите ПВЗ или адрес до двери")

    client = await session.get(Client, order.client_id)
    if client is None or not client.phone:
        raise yd.YandexDeliveryError("нет телефона получателя")

    cfg = await load_yandex_cfg(session)
    lat, lon = latitude, longitude
    if not pickup_point_id and lat is None and cfg.get("geocoder_apikey"):
        lat, lon = await yd.geocode(cfg["geocoder_apikey"], to_address or "")
    request = yd.build_request(
        cfg,
        order_id=order.id,
        item_price_rub=_item_price(order),
        recipient_name=client.nickname or "Получатель",
        recipient_phone=client.phone,
        pickup_point_id=pickup_point_id,
        address=to_address,
        latitude=lat,
        longitude=lon,
    )
    offers = [o for o in await yd.offers_create(cfg, request) if o.get("offer_id")]
    if not offers:
        raise yd.YandexDeliveryError("нет доступных тарифов на этот адрес")
    chosen = min(offers, key=lambda o: float(o.get("delivery_cost") or 0))
    stored = encode_destination(
        pickup_point_id=pickup_point_id,
        to_address=to_address,
        label=label,
    )
    try:
        await _save_quoted(
            session,
            order,
            service=DeliveryService.YANDEX,
            stored=stored,
            cost=float(chosen["delivery_cost"]),
            chosen_label="Яндекс Доставку",
        )
    except InvalidTransition as e:
        raise yd.YandexDeliveryError(str(e)) from e
    return {
        "delivery_sum": float(chosen["delivery_cost"]),
        "period_min": _days_until(chosen.get("delivery_from")),
        "period_max": _days_until(chosen.get("delivery_to")),
        "tariff_code": 0,
        "address": decode_destination(stored)["label"],
        "service": "yandex",
    }


async def fulfill(session: AsyncSession, order: Order, client: Client | None) -> dict | None:
    """Создать заявку выбранной службы по сохранённому адресу."""
    if order.tracking_code:
        return None
    if order.delivery_service == DeliveryService.YANDEX:
        return await _fulfill_yandex(session, order, client)
    return await _fulfill_cdek(session, order, client)


async def _fulfill_cdek(
    session: AsyncSession, order: Order, client: Client | None
) -> dict | None:
    """Создать заявку СДЭК по сохранённому адресу. Ошибки не откатывают оплату."""
    if order.tracking_code and order.delivery_service == DeliveryService.CDEK:
        return None
    dest = decode_destination(order.delivery_address)
    if not (dest.get("pickup_point_id") or dest.get("to_address")):
        if client is not None:
            _notify(
                session,
                client,
                order.id,
                "Оплата доставки получена, но адрес не сохранился. "
                "Напишите нам — оформим отправку вручную.",
            )
        return None
    if client is None or not client.phone:
        if client is not None:
            _notify(
                session,
                client,
                order.id,
                "Оплата доставки получена, но нет телефона получателя. "
                "Напишите нам — оформим отправку.",
            )
        return None

    try:
        cfg = await load_cfg(session)
        created = await cdek.create_order(
            cfg,
            order_id=order.id,
            item_price_rub=_item_price(order),
            recipient_name=client.nickname or "Получатель",
            recipient_phone=client.phone,
            delivery_point=dest.get("pickup_point_id"),
            to_postal=dest.get("to_postal"),
            to_address=dest.get("to_address"),
        )
    except cdek.CdekError as e:
        if client is not None:
            _notify(
                session,
                client,
                order.id,
                f"Оплата доставки получена, заявку СДЭК оформим вручную ({e}).",
            )
        return None

    order.delivery_service = DeliveryService.CDEK
    order.tracking_code = created.get("cdek_number") or created["uuid"]
    track = created.get("cdek_number") or created["uuid"]
    if client is not None:
        _notify(
            session,
            client,
            order.id,
            f"Заявка СДЭК создана. Номер отслеживания: {track}. "
            "Когда посылка будет в пути — напишем.",
        )
    return created


async def _fulfill_yandex(
    session: AsyncSession, order: Order, client: Client | None
) -> dict | None:
    from app.services import yandex_delivery as yd

    dest = decode_destination(order.delivery_address)
    if not (dest.get("pickup_point_id") or dest.get("to_address")):
        if client is not None:
            _notify(
                session,
                client,
                order.id,
                "Оплата доставки получена, но адрес не сохранился. "
                "Напишите нам — оформим отправку вручную.",
            )
        return None
    if client is None or not client.phone:
        if client is not None:
            _notify(
                session,
                client,
                order.id,
                "Оплата доставки получена, но нет телефона получателя. "
                "Напишите нам — оформим отправку.",
            )
        return None

    try:
        cfg = await load_yandex_cfg(session)
        lat = lon = None
        if not dest.get("pickup_point_id") and cfg.get("geocoder_apikey"):
            lat, lon = await yd.geocode(cfg["geocoder_apikey"], dest.get("to_address") or "")
        request = yd.build_request(
            cfg,
            order_id=order.id,
            item_price_rub=_item_price(order),
            recipient_name=client.nickname or "Получатель",
            recipient_phone=client.phone,
            pickup_point_id=dest.get("pickup_point_id"),
            address=dest.get("to_address"),
            latitude=lat,
            longitude=lon,
        )
        offers = [o for o in await yd.offers_create(cfg, request) if o.get("offer_id")]
        if not offers:
            raise yd.YandexDeliveryError("нет доступных тарифов")
        chosen = min(offers, key=lambda o: float(o.get("delivery_cost") or 0))
        request_id = await yd.offers_confirm(cfg, chosen["offer_id"])
    except yd.YandexDeliveryError as e:
        if client is not None:
            _notify(
                session,
                client,
                order.id,
                f"Оплата доставки получена, заявку Яндекса оформим вручную ({e}).",
            )
        return None

    order.delivery_service = DeliveryService.YANDEX
    order.tracking_code = request_id
    if client is not None:
        _notify(
            session,
            client,
            order.id,
            f"Заявка Яндекс Доставки создана. Номер: {request_id}. "
            "Когда посылка будет в пути — напишем.",
        )
    return {"request_id": request_id}
