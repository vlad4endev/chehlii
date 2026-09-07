"""Переписка «Поможем выбрать»: треды, сообщения, сценарии, outbox."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ConsultSender, ConsultStatus, OrderStatus
from app.models.client import Client
from app.models.consult import ConsultMessage, ConsultThread
from app.models.messaging import BotMessage, OutboundMessage
from app.models.order import Order

PREVIEW_LEN = 140

_MEDIA_LABEL = {
    "image": "фото",
    "video": "видео",
    "audio": "голосовое",
    "file": "файл",
    "video_note": "кружок",
}

# Сценарии, которые меняют FSM клиента (остальные msg_* — только текст).
GUIDE_SCENARIOS: dict[str, str] = {
    "msg_002": "waiting_contact",
    "msg_003": "clear",
    "msg_006а": "waiting_name",
    "msg_006б": "waiting_materials",
    "msg_help": "consulting",
    "msg_help_close": "clear",
}

NEEDS_ORDER = frozenset({"msg_006а", "msg_006б"})

_DONE_STATUSES = frozenset(
    {
        OrderStatus.CANCELLED,
        OrderStatus.DELIVERED,
        OrderStatus.REVIEW_OFFERED,
        OrderStatus.REVIEW_RECEIVED,
    }
)

_FALLBACK_TEXTS: dict[str, str] = {
    "msg_help_close": (
        "Диалог закрыт. Если понадобится помощь, снова нажмите «Поможем выбрать»."
    ),
}


def preview_text(text: str | None, media: list | None) -> str:
    """Короткий превью для списка диалогов."""
    body = (text or "").strip()
    if body:
        return body if len(body) <= PREVIEW_LEN else body[: PREVIEW_LEN - 1] + "…"
    items = media or []
    if not items:
        return "Сообщение"
    kinds = [
        _MEDIA_LABEL.get(str(m.get("type") or ""), "файл")
        for m in items
        if isinstance(m, dict)
    ]
    if not kinds:
        return "Вложение"
    if len(kinds) == 1:
        return kinds[0].capitalize()
    return f"{len(kinds)} вложения"


def message_kind(text: str | None, media: list | None) -> str:
    items = [m for m in (media or []) if isinstance(m, dict) and m.get("url")]
    if not items:
        return "text"
    if len(items) > 1:
        return "album"
    return str(items[0].get("type") or "file")


def fsm_state_for(code: str) -> str | None:
    """None — сценарий без смены FSM (только текст)."""
    return GUIDE_SCENARIOS.get(code)


async def get_or_create_thread(session: AsyncSession, client_id: int) -> ConsultThread:
    row = await session.scalar(select(ConsultThread).where(ConsultThread.client_id == client_id))
    if row is not None:
        return row
    row = ConsultThread(client_id=client_id, status=ConsultStatus.OPEN, unread_admin=0)
    session.add(row)
    await session.flush()
    return row


async def bot_message_text(session: AsyncSession, code: str) -> str:
    row = await session.scalar(select(BotMessage).where(BotMessage.code == code))
    if row and row.text:
        return row.text
    return _FALLBACK_TEXTS.get(code, code)


async def latest_open_order(session: AsyncSession, client_id: int) -> Order | None:
    """Последний незавершённый заказ клиента — для сценариев имени/материалов."""
    return await session.scalar(
        select(Order)
        .where(
            Order.client_id == client_id,
            Order.deleted_at.is_(None),
            Order.status.notin_(_DONE_STATUSES),
        )
        .order_by(Order.id.desc())
        .limit(1)
    )


async def add_message(
    session: AsyncSession,
    *,
    thread: ConsultThread,
    sender: ConsultSender,
    text: str | None,
    media: list | None,
    admin_user_id: int | None = None,
    kind: str | None = None,
    reopen: bool = True,
) -> ConsultMessage:
    """Добавить сообщение и обновить сводку треда. Коммит — на вызывающей стороне."""
    clean_media = [m for m in (media or []) if isinstance(m, dict) and m.get("url")] or None
    # Для scenario в media может быть мета без url — сохраняем как есть.
    if kind == "scenario" and media and clean_media is None:
        clean_media = [m for m in media if isinstance(m, dict)] or None
    body = (text or "").strip() or None
    msg = ConsultMessage(
        thread_id=thread.id,
        sender=sender,
        admin_user_id=admin_user_id,
        kind=kind or message_kind(body, clean_media),
        text=body,
        media=clean_media,
    )
    session.add(msg)
    now = datetime.now(UTC)
    thread.last_message_at = now
    thread.last_preview = preview_text(body, clean_media)
    thread.last_sender = sender
    if reopen:
        thread.status = ConsultStatus.OPEN
        thread.closed_at = None
    if sender == ConsultSender.CLIENT:
        thread.unread_admin = int(thread.unread_admin or 0) + 1
    else:
        thread.unread_admin = 0
    await session.flush()
    return msg


async def enqueue_admin_reply(session: AsyncSession, client: Client, msg: ConsultMessage) -> None:
    """Поставить ответ продавца в outbox — бот доставит в Telegram/MAX."""
    media = list(msg.media or [])
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            kind="album" if media else "text",
            text=msg.text,
            media=media or None,
        )
    )


async def enqueue_typing(session: AsyncSession, client: Client) -> bool:
    """Сигнал «печатает…» в outbox. Не дублируем, если уже есть неотправенный typing."""
    pending = await session.scalar(
        select(OutboundMessage.id).where(
            OutboundMessage.client_id == client.id,
            OutboundMessage.kind == "typing",
            OutboundMessage.sent_at.is_(None),
        )
    )
    if pending is not None:
        return False
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            kind="typing",
            text=None,
        )
    )
    return True


async def enqueue_scenario(
    session: AsyncSession,
    client: Client,
    *,
    text: str,
    code: str,
    state: str | None,
    order_id: int | None,
) -> None:
    """Outbox kind=scenario: бот шлёт текст и (для TG) сразу ставит FSM."""
    meta: list[dict] = [{"type": "scenario", "code": code}]
    if state:
        meta[0]["state"] = state
    session.add(
        OutboundMessage(
            client_id=client.id,
            channel=client.channel,
            channel_user_id=client.channel_user_id,
            order_id=order_id,
            kind="scenario",
            text=text,
            media=meta,
        )
    )


async def send_scenario(
    session: AsyncSession,
    *,
    thread: ConsultThread,
    client: Client,
    code: str,
    admin_user_id: int | None,
) -> ConsultMessage:
    """Отправить сценарий бота: запись в тред + pending_fsm + outbox."""
    text = await bot_message_text(session, code)
    state = fsm_state_for(code)
    order_id: int | None = None
    if code in NEEDS_ORDER:
        order = await latest_open_order(session, client.id)
        if order is None:
            raise ValueError("Нет активного заказа — сначала оформите чехол в каталоге.")
        order_id = order.id
    meta = [{"type": "scenario", "code": code}]
    if state:
        meta[0]["state"] = state
    msg = await add_message(
        session,
        thread=thread,
        sender=ConsultSender.ADMIN,
        text=text,
        media=meta,
        admin_user_id=admin_user_id,
        kind="scenario",
    )
    if state:
        pending: dict = {"state": state, "code": code}
        if order_id is not None:
            pending["order_id"] = order_id
        thread.pending_fsm = pending
    else:
        # Только текст — выходим из консультации не трогаем FSM.
        pass
    await enqueue_scenario(
        session, client, text=text, code=code, state=state, order_id=order_id
    )
    await session.flush()
    return msg


async def close_with_notify(
    session: AsyncSession,
    *,
    thread: ConsultThread,
    client: Client,
    admin_user_id: int | None,
) -> ConsultMessage | None:
    """Закрыть диалог и один раз оповестить клиента. Повторное закрытие — без письма."""
    if thread.status == ConsultStatus.CLOSED:
        return None
    text = await bot_message_text(session, "msg_help_close")
    msg = await add_message(
        session,
        thread=thread,
        sender=ConsultSender.ADMIN,
        text=text,
        media=[{"type": "scenario", "code": "msg_help_close", "state": "clear"}],
        admin_user_id=admin_user_id,
        kind="scenario",
        reopen=False,
    )
    thread.pending_fsm = {"state": "clear", "code": "msg_help_close"}
    thread.status = ConsultStatus.CLOSED
    thread.closed_at = datetime.now(UTC)
    thread.unread_admin = 0
    await enqueue_scenario(
        session,
        client,
        text=text,
        code="msg_help_close",
        state="clear",
        order_id=None,
    )
    await session.flush()
    return msg


async def take_pending_fsm(
    session: AsyncSession, *, client_id: int
) -> dict | None:
    """Снять pending_fsm с треда клиента (для outer middleware бота)."""
    thread = await session.scalar(
        select(ConsultThread).where(ConsultThread.client_id == client_id)
    )
    if thread is None or not thread.pending_fsm:
        return None
    pending = dict(thread.pending_fsm)
    thread.pending_fsm = None
    await session.flush()
    return pending
