"""Опрос службы доставки: актуальный трек и перевод статуса «Отправлен»/«Доставлен»."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import DeliveryService, OrderStatus
from app.models.client import Client
from app.models.order import Order, OrderStatusHistory
from app.services import cdek, cdek_checkout, ozon_delivery, yandex_delivery
from app.services.order_status_notify import (
    enqueue_delivered,
    enqueue_shipped,
    offer_review_after_delivered,
)
from app.services.shipping_info import tracking_url as build_tracking_url


@dataclass
class SyncResult:
    carrier_status: str | None = None
    carrier_status_name: str | None = None
    tracking_url: str | None = None
    order_status_changed: bool = False


async def _advance(session: AsyncSession, order: Order, new: OrderStatus, trigger: str) -> bool:
    """Та же семантика, что у delivery._advance: идемпотентно + уведомление клиенту."""
    if order.status == new:
        return False
    if order.status in (
        OrderStatus.DELIVERED,
        OrderStatus.REVIEW_OFFERED,
        OrderStatus.REVIEW_RECEIVED,
    ):
        return False
    order.status = new
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=new,
            changed_by="system",
            trigger=trigger,
            created_at=datetime.now(UTC),
        )
    )
    client = await session.get(Client, order.client_id)
    if new == OrderStatus.DELIVERED:
        await enqueue_delivered(session, order, client)
        await offer_review_after_delivered(session, order, client, trigger=trigger)
    else:
        await enqueue_shipped(session, order, client)
    await session.commit()
    return True


async def sync_tracking(session: AsyncSession, order: Order) -> SyncResult:
    """Подтянуть трек/статус у выбранной службы. Без tracking_code — ошибка вызывающего."""
    service = (order.delivery_service or "").lower()
    if service == DeliveryService.CDEK:
        return await _sync_cdek(session, order)
    if service == DeliveryService.YANDEX:
        return await _sync_yandex(session, order)
    if service == DeliveryService.OZON:
        return await _sync_ozon(session, order)
    raise ValueError(f"Неизвестная служба доставки: {order.delivery_service}")


async def _sync_cdek(session: AsyncSession, order: Order) -> SyncResult:
    cfg = await cdek_checkout.load_cfg(session)
    raw = await cdek.get_order(cfg, order.tracking_code or f"casetop-{order.id}")
    info = cdek.order_info(raw)
    if info.get("cdek_number"):
        order.tracking_code = str(info["cdek_number"])
    mapped = cdek.map_status(info.get("status"))
    changed = False
    if mapped:
        status = OrderStatus.DELIVERED if mapped == "delivered" else OrderStatus.SHIPPED
        changed = await _advance(session, order, status, f"СДЭК: {info.get('status')}")
    if not changed:
        await session.commit()
    return SyncResult(
        carrier_status=info.get("status"),
        carrier_status_name=info.get("status_name"),
        tracking_url=build_tracking_url("cdek", order.tracking_code),
        order_status_changed=changed,
    )


async def _sync_yandex(session: AsyncSession, order: Order) -> SyncResult:
    cfg = await cdek_checkout.load_yandex_cfg(session)
    info = await yandex_delivery.request_info(cfg, order.tracking_code or "")
    # tracking_code = request_id заявки — им же ходят status/label, не подменяем.
    # Для UI: courier_order_id в подписи статуса, ссылка — sharing_url.
    mapped = yandex_delivery.map_status(info.get("status"))
    changed = False
    if mapped:
        status = OrderStatus.DELIVERED if mapped == "delivered" else OrderStatus.SHIPPED
        changed = await _advance(session, order, status, f"Яндекс: {info.get('status')}")
    if not changed:
        await session.commit()
    courier = info.get("courier_order_id")
    desc = info.get("description") or info.get("status")
    if courier:
        status_name = f"{desc} · № {courier}" if desc else f"№ {courier}"
    else:
        status_name = desc
    return SyncResult(
        carrier_status=info.get("status"),
        carrier_status_name=status_name,
        tracking_url=build_tracking_url(
            "yandex",
            order.tracking_code,
            sharing_url=info.get("sharing_url"),
        ),
        order_status_changed=changed,
    )


async def _sync_ozon(session: AsyncSession, order: Order) -> SyncResult:
    cfg = await cdek_checkout.load_ozon_cfg(session)
    info = await ozon_delivery.posting_info(cfg, order.tracking_code or "")
    status_code = ozon_delivery.extract_status(info)
    mapped = ozon_delivery.map_status(status_code)
    changed = False
    if mapped:
        status = OrderStatus.DELIVERED if mapped == "delivered" else OrderStatus.SHIPPED
        changed = await _advance(session, order, status, f"Ozon: {status_code}")
    if not changed:
        await session.commit()
    return SyncResult(
        carrier_status=status_code,
        carrier_status_name=status_code,
        tracking_url=build_tracking_url("ozon", order.tracking_code),
        order_status_changed=changed,
    )


async def fetch_label_pdf(session: AsyncSession, order: Order) -> bytes:
    """PDF ярлыка от службы. Без заявки — ValueError."""
    if not order.tracking_code or not order.delivery_service:
        raise ValueError("Заявка в службе доставки ещё не создана")
    service = order.delivery_service.lower()
    if service == DeliveryService.CDEK:
        cfg = await cdek_checkout.load_cfg(session)
        return await cdek.generate_label(cfg, order.tracking_code, fmt="A4")
    if service == DeliveryService.YANDEX:
        cfg = await cdek_checkout.load_yandex_cfg(session)
        return await yandex_delivery.generate_label(cfg, order.tracking_code, size_mm="210x297")
    if service == DeliveryService.OZON:
        cfg = await cdek_checkout.load_ozon_cfg(session)
        return await ozon_delivery.generate_label(cfg, order.tracking_code)
    raise ValueError(f"Неизвестная служба: {order.delivery_service}")
