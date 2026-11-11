import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models import AppUser, NotificationOutbox, OutboxStatus


STATUS_LABELS = {
    "TO_BUY": "ожидает покупки",
    "ORDERED": "заказан",
    "PURCHASED_OFFLINE": "куплен офлайн",
    "ON_THE_WAY_TO_US": "едет к нам",
    "READY_FOR_PICKUP": "готов к получению",
    "RECEIVED": "получен на складе",
    "ASSIGNED_TO_SHIPMENT": "добавлен в отправление",
    "SHIPPED": "отправлен",
    "DELIVERED": "доставлен",
    "CANCELLED": "отменён",
    "RETURN_IN_PROGRESS": "оформляется возврат",
    "RETURNED": "возвращён",
}


def notification_text(event: NotificationOutbox) -> str:
    if event.event_type == "SHIPMENT_TRACKING_UPDATED":
        return (
            f"Для заказа {event.payload.get('item_id', '')} добавлен трек-номер.\n"
            f"Служба доставки: {event.payload.get('carrier', '')}.\n"
            f"Трек-номер: {event.payload.get('tracking_number', '')}."
        )
    target = str(event.payload.get("to", ""))
    item_id = str(event.payload.get("item_id", ""))
    text = f"Статус заказа {item_id} изменён: {STATUS_LABELS.get(target, target)}."
    tracking_number = event.payload.get("tracking_number")
    if tracking_number:
        text += f"\nТрек-номер отправления: {tracking_number}."
    return text


async def deliver_one(bot: Bot) -> bool:
    async with SessionFactory() as session, session.begin():
        event = await session.scalar(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == OutboxStatus.PENDING,
                NotificationOutbox.available_at <= datetime.now(timezone.utc),
            )
            .order_by(NotificationOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return False
        user = await session.get(AppUser, event.recipient_user_id)
        event.status = OutboxStatus.PROCESSING
        event.attempts += 1
        try:
            if user is None:
                raise RuntimeError("recipient user not found")
            await bot.send_message(user.telegram_user_id, notification_text(event))
            event.status = OutboxStatus.SENT
            event.last_error = None
        except Exception as exc:
            event.last_error = str(exc)[:2000]
            if event.attempts >= 5:
                event.status = OutboxStatus.FAILED
            else:
                event.status = OutboxStatus.PENDING
                event.available_at = datetime.now(timezone.utc) + timedelta(
                    seconds=min(300, 5 * (2 ** (event.attempts - 1)))
                )
        return True


async def notification_worker(bot: Bot) -> None:
    while True:
        processed = await deliver_one(bot)
        if not processed:
            await asyncio.sleep(2)
