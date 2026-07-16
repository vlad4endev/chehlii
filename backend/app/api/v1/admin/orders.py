"""Заказы (AdminUI). Доступ — обе роли, но финансовые поля скрыты от Дизайнера
на уровне сериализации (ТЗ). Смена статусов — через машину состояний с ролевыми
ограничениями. Выгрузка в Excel — только Админ.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.admin.deps import AdminOnly, CurrentAdmin, is_admin
from app.core.database import get_session
from app.enums import AdminRole, CaseBranch, Channel, OrderStatus, PaymentStatus
from app.models.admin_user import AdminUser
from app.models.catalog import CaseType
from app.models.client import Client
from app.models.messaging import BotMessage, OutboundMessage
from app.models.order import Order, OrderStatusHistory
from app.services import integrations
from app.services import order_state_machine as fsm
from app.services import yandex_disk

router = APIRouter()

# Статусы, которые Дизайнер может ставить вручную (ТЗ).
DESIGNER_STATUSES = {
    OrderStatus.HANDED_TO_DESIGN,
    OrderStatus.DESIGN_IN_PROGRESS,
    OrderStatus.CANCELLED,
}

STATUS_LABELS: dict[str, str] = {
    "case_type_selected": "Выбран тип чехла",
    "model_selected": "Выбрана модель",
    "case_confirmed": "Согласован чехол",
    "materials_submitted": "Отправка материала",
    "prepayment_issued": "Предоплата выставлена",
    "prepayment_paid": "Предоплата прошла",
    "handed_to_design": "Передан в дизайн",
    "design_in_progress": "Дизайн в процессе",
    "mockup_sent": "Отправка макета",
    "mockup_approval": "Согласование макета",
    "mockup_revision": "Пересогласование макета",
    "postpayment_issued": "Постоплата выставлена",
    "postpayment_paid": "Постоплата прошла",
    "cancelled": "Отменён",
    "delivery_service_selection": "Выбор службы доставки",
    "delivery_address_selection": "Выбор адреса",
    "delivery_payment": "Оплата доставки",
    "shipped": "Заказ отправлен",
    "delivered": "Заказ получен",
    "review_offered": "Предложение об отзыве",
    "review_received": "Отзыв получен",
}


class OrderRow(BaseModel):
    id: int
    created_at: datetime
    channel: Channel
    client_name: str | None
    client_phone: str | None
    case_name: str | None
    model_name: str | None
    case_photo_url: str | None  # фото чехла: под модель → обложка типа
    is_custom: bool | None
    branch: CaseBranch | None
    status: OrderStatus
    status_label: str
    payment_status: PaymentStatus | None
    final_price: float | None  # None для Дизайнера


class StatusOption(BaseModel):
    value: OrderStatus
    label: str


class StatusEvent(BaseModel):
    status: OrderStatus
    status_label: str
    changed_by: str | None
    trigger: str | None
    created_at: datetime


class OrderDetail(OrderRow):
    materials_text: str | None
    materials_files: list | None
    custom_text: str | None
    mockup_url: str | None
    delivery_service: str | None
    delivery_address: str | None
    tracking_code: str | None
    # Финансы — None для Дизайнера
    cost: float | None
    margin: float | None
    total_discount: float | None
    delivery_cost: float | None
    allowed_next: list[StatusOption]
    history: list[StatusEvent]


def _case_photo(case: CaseType | None, model_name: str | None) -> str | None:
    """Фото чехла для заказа: под конкретную модель iPhone → обложка типа."""
    if case is None:
        return None
    if model_name:
        for m in case.models:
            if m.model_name == model_name and m.photo_url:
                return m.photo_url
    return case.photo_url


def _row(order: Order, client: Client, case: CaseType | None, *, admin: bool) -> OrderRow:
    return OrderRow(
        id=order.id,
        created_at=order.created_at,
        channel=client.channel,
        client_name=client.nickname,
        client_phone=client.phone,
        case_name=case.name if case else None,
        model_name=order.model_name,
        case_photo_url=_case_photo(case, order.model_name),
        is_custom=case.is_custom if case else order.branch == CaseBranch.CUSTOM,
        branch=order.branch,
        status=order.status,
        status_label=STATUS_LABELS.get(order.status, order.status),
        payment_status=order.payment_status,
        final_price=float(order.final_price) if admin and order.final_price is not None else None,
    )


def _allowed_next(order: Order, role: AdminRole) -> list[StatusOption]:
    nxt = [t.to for t in fsm.allowed_next(order.status)]
    if role != AdminRole.ADMIN:
        nxt = [s for s in nxt if s in DESIGNER_STATUSES]
    return [StatusOption(value=s, label=STATUS_LABELS.get(s, s)) for s in nxt]


@router.get("", response_model=list[OrderRow])
async def list_orders(
    user: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    channel: Channel | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[OrderRow]:
    stmt = (
        select(Order, Client, CaseType)
        .join(Client, Order.client_id == Client.id)
        .outerjoin(CaseType, Order.case_type_id == CaseType.id)
        .options(selectinload(CaseType.models))
        .order_by(Order.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if channel:
        stmt = stmt.where(Client.channel == channel)
    if date_from:
        stmt = stmt.where(Order.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(Order.created_at <= datetime.combine(date_to, datetime.max.time()))
    if q:
        term = f"%{q.strip()}%"
        conds = [Client.phone.ilike(term), Client.nickname.ilike(term)]
        if q.strip().isdigit():
            conds.append(Order.id == int(q.strip()))
        stmt = stmt.where(or_(*conds))

    admin = is_admin(user)
    rows = await session.execute(stmt)
    return [_row(o, c, ct, admin=admin) for o, c, ct in rows.all()]


# Определён до /{order_id}, иначе путь "export.xlsx" перехватится параметром.
@router.get("/export.xlsx")
async def export_xlsx(
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    from openpyxl import Workbook

    rows = await session.execute(
        select(Order, Client, CaseType)
        .join(Client, Order.client_id == Client.id)
        .outerjoin(CaseType, Order.case_type_id == CaseType.id)
        .order_by(Order.id)
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Заказы"
    ws.append(
        ["ID", "Дата", "Канал", "Клиент", "Телефон", "Тип", "Модель", "Статус",
         "Себес", "Маржа", "Скидка %", "Доставка", "Итог", "Оплата"]
    )
    for o, c, ct in rows.all():
        ws.append([
            o.id,
            o.created_at.strftime("%d.%m.%Y %H:%M") if o.created_at else "",
            c.channel,
            c.nickname or "",
            c.phone or "",
            ct.name if ct else "",
            o.model_name or "",
            STATUS_LABELS.get(o.status, o.status),
            float(o.cost) if o.cost is not None else "",
            float(o.margin) if o.margin is not None else "",
            float(o.total_discount) if o.total_discount is not None else "",
            float(o.delivery_cost) if o.delivery_cost is not None else "",
            float(o.final_price) if o.final_price is not None else "",
            o.payment_status or "",
        ])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="orders.xlsx"'},
    )


async def _load(session: AsyncSession, order_id: int) -> tuple[Order, Client, CaseType | None]:
    # populate_existing — чтобы после смены статуса ответ содержал свежую историю,
    # а не закешированную коллекцию (expire_on_commit=False).
    order = await session.scalar(
        select(Order)
        .options(selectinload(Order.status_history))
        .where(Order.id == order_id)
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    client = await session.get(Client, order.client_id)
    case = (
        await session.scalar(
            select(CaseType)
            .options(selectinload(CaseType.models))
            .where(CaseType.id == order.case_type_id)
        )
        if order.case_type_id
        else None
    )
    return order, client, case


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: int,
    user: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderDetail:
    order, client, case = await _load(session, order_id)
    admin = is_admin(user)
    base = _row(order, client, case, admin=admin)
    history = sorted(order.status_history, key=lambda h: h.created_at)
    return OrderDetail(
        **base.model_dump(),
        materials_text=order.materials_text,
        materials_files=order.materials_files,
        custom_text=order.custom_text,
        mockup_url=order.mockup_url,
        delivery_service=order.delivery_service,
        delivery_address=order.delivery_address,
        tracking_code=order.tracking_code,
        cost=float(order.cost) if admin and order.cost is not None else None,
        margin=float(order.margin) if admin and order.margin is not None else None,
        total_discount=float(order.total_discount)
        if admin and order.total_discount is not None
        else None,
        delivery_cost=float(order.delivery_cost)
        if admin and order.delivery_cost is not None
        else None,
        allowed_next=_allowed_next(order, user.role),
        history=[
            StatusEvent(
                status=h.status,
                status_label=STATUS_LABELS.get(h.status, h.status),
                changed_by=h.changed_by,
                trigger=h.trigger,
                created_at=h.created_at,
            )
            for h in history
        ],
    )


class StatusChangeIn(BaseModel):
    status: OrderStatus


async def _record(session: AsyncSession, order: Order, new: OrderStatus, by: AdminUser) -> None:
    order.status = new
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=new,
            changed_by=str(by.id),
            trigger=f"AdminUI: {by.full_name or by.email}",
            created_at=datetime.now(UTC),
        )
    )


@router.patch("/{order_id}/status", response_model=OrderDetail)
async def change_status(
    order_id: int,
    payload: StatusChangeIn,
    user: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderDetail:
    order, _, _ = await _load(session, order_id)
    if user.role != AdminRole.ADMIN and payload.status not in DESIGNER_STATUSES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Дизайнеру недоступен этот статус")
    if not fsm.can_transition(order.status, payload.status):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недопустимый переход: {STATUS_LABELS.get(order.status)} → "
            f"{STATUS_LABELS.get(payload.status)}",
        )
    await _record(session, order, payload.status, user)
    await session.commit()
    return await get_order(order_id, user, session)


_MOCKUP_DEFAULT_TEXT = (
    "Дизайнер подготовил макет вашего чехла ✨\n"
    "Посмотрите файл выше и подтвердите — или отправьте на доработку."
)


@router.post("/{order_id}/mockup", response_model=OrderDetail)
async def upload_mockup(
    order_id: int,
    user: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File()],
) -> OrderDetail:
    """Триггерная цепочка передачи макета (ТЗ v2.0): дизайнер грузит файл →
    (1) файл на Яндекс Диск /orders/{id}/design/, (2) статус «Отправка макета»,
    (3) заявка в outbox — бот доставит клиенту с кнопками «Подтвердить/Переделать».
    """
    order, client, _ = await _load(session, order_id)
    content = await file.read()
    filename = (file.filename or f"mockup_{order_id}").replace("/", "_")

    token = await integrations.get(session, "yandex_disk.oauth_token")
    root = await integrations.get(session, "yandex_disk.root", "/chechlii/orders")
    if not token:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Яндекс.Диск не настроен — задайте OAuth-токен в разделе «Настройки → Интеграции».",
        )
    try:
        url = await yandex_disk.upload(
            yandex_disk.design_path(root, order_id, filename), content, token=token
        )
    except yandex_disk.YandexDiskError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Яндекс.Диск: {e}") from e

    order.mockup_url = url
    if fsm.can_transition(order.status, OrderStatus.MOCKUP_SENT):
        await _record(session, order, OrderStatus.MOCKUP_SENT, user)

    msg = await session.scalar(select(BotMessage).where(BotMessage.code == "msg_009аб"))
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            order_id=order.id,
            kind="mockup",
            text=(msg.text if msg else _MOCKUP_DEFAULT_TEXT),
            attachment_url=url,
        )
    )
    await session.commit()
    return await get_order(order_id, user, session)
