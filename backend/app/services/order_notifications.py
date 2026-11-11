from sqlalchemy import select

from app.models import Customer, NotificationOutbox, StylistOrder


async def notify_order(session, order, text):
    recipient = await session.scalar(
        select(Customer.app_user_id).where(Customer.id == order.customer_id)
    )
    for user_id in {order.stylist_id, recipient} - {None}:
        session.add(
            NotificationOutbox(
                recipient_user_id=user_id,
                event_type="ORDER_MESSAGE",
                payload={"text": f"{order.number}: {text}"},
            )
        )


async def notify_stylist_item(session, item, payload):
    if item.order_id:
        order = await session.get(StylistOrder, item.order_id)
        recipient = await session.scalar(
            select(Customer.app_user_id).where(Customer.id == item.customer_id)
        )
        if order and order.stylist_id != recipient:
            session.add(
                NotificationOutbox(
                    recipient_user_id=order.stylist_id,
                    event_type="ITEM_STATUS_CHANGED",
                    payload={**payload, "order_number": order.number},
                )
            )
