from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestActor, get_request_actor
from app.core.config import get_settings
from app.db.session import get_session
from app.models import (
    Customer,
    CustomerAddress,
    Item,
    ItemStatus,
    OrderPayment,
    OrderQuote,
    OrderRefund,
    StylistOrder,
    UserRole,
)
from app.schemas.orders import (
    CancelInput,
    ItemInput,
    NewOrderInput,
    QuoteInput,
    RecipientInput,
    ShippingCostInput,
)
from app.services.orders import OrderError, OrderService
from app.services.rates import current_rate

router = APIRouter(prefix="/api/v1", tags=["stylist-orders"])


def record(value, fields):
    from decimal import Decimal

    return jsonable_encoder(
        {
            key: str(getattr(value, key))
            if isinstance(getattr(value, key), Decimal)
            else getattr(value, key)
            for key in fields.split()
        }
    )


async def order_details(session, order):
    result = record(
        order,
        "id number stylist_id customer_id address_snapshot state active_quote_id created_at updated_at",
    )
    items = (
        await session.scalars(
            select(Item).where(Item.order_id == order.id).order_by(Item.created_at)
        )
    ).all()
    quotes = (
        await session.scalars(
            select(OrderQuote)
            .where(OrderQuote.order_id == order.id)
            .order_by(OrderQuote.created_at)
        )
    ).all()
    payments = (
        await session.scalars(select(OrderPayment).where(OrderPayment.order_id == order.id))
    ).all()
    refunds = (
        await session.scalars(select(OrderRefund).where(OrderRefund.order_id == order.id))
    ).all()
    result["items"] = [
        record(i, "id product_url product_name size color quantity listed_price status")
        for i in items
    ]
    result["pending_urls"] = (order.intake_snapshot or {}).get("urls", [])
    result["quotes"] = [
        record(
            q, "id rate_date eur_rub_rate goods_eur total_eur due_rub close_order state created_at"
        )
        for q in quotes
    ]
    result["payments"] = [record(p, "id quote_id paid_at amount_rub") for p in payments]
    result["refunds"] = [record(r, "id item_id amount_rub reason state") for r in refunds]
    # Decimal is serialized explicitly as a string for stable financial display.
    from decimal import Decimal

    from app.domain.money import quantize_money

    goods = sum(
        (
            i.listed_price * i.quantity
            for i in items
            if i.status
            not in (ItemStatus.CANCELLED, ItemStatus.RETURN_IN_PROGRESS, ItemStatus.RETURNED)
        ),
        Decimal(0),
    )
    result["goods_eur"] = str(goods)
    result["total_eur"] = str(quantize_money(goods * Decimal("1.20")))
    result["paid_rub"] = str(sum((p.amount_rub for p in payments), Decimal(0)))
    result["refund_rub"] = str(sum((r.amount_rub for r in refunds), Decimal(0)))
    from app.models import CustomerShipment, ShipmentItem

    shipments = (
        await session.scalars(
            select(CustomerShipment)
            .join(ShipmentItem)
            .join(Item)
            .where(Item.order_id == order.id)
            .distinct()
        )
    ).all()
    result["shipments"] = [
        record(s, "id carrier tracking_number status shipping_cost currency") for s in shipments
    ]
    return result


@router.get("/recipients")
async def recipients(
    actor: RequestActor = Depends(get_request_actor), session: AsyncSession = Depends(get_session)
):
    query = select(Customer, CustomerAddress).join(
        CustomerAddress, CustomerAddress.customer_id == Customer.id
    )
    if actor.role != UserRole.ADMIN:
        query = query.where(Customer.stylist_id == actor.app_user_id)
    return [
        dict(
            record(c, "id display_name phone telegram_username"),
            address=record(
                a,
                "id recipient_name country_code postal_code region city address_line1 address_line2",
            ),
        )
        for c, a in (await session.execute(query.order_by(Customer.display_name))).all()
    ]


@router.post("/recipients")
async def create_recipient(
    command: RecipientInput,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    customer = Customer(
        stylist_id=actor.app_user_id,
        display_name=command.recipient_name,
        phone=command.phone,
        telegram_username=command.telegram_username,
    )
    session.add(customer)
    await session.flush()
    address = CustomerAddress(
        customer_id=customer.id,
        label="Основной адрес",
        is_default=True,
        country_code="RU",
        **command.model_dump(exclude={"telegram_username"}),
    )
    session.add(address)
    await session.commit()
    return {"customer_id": str(customer.id), "address_id": str(address.id)}


@router.get("/orders")
async def orders(
    actor: RequestActor = Depends(get_request_actor), session: AsyncSession = Depends(get_session)
):
    query = select(StylistOrder).order_by(StylistOrder.created_at.desc())
    if actor.role != UserRole.ADMIN:
        query = query.where(StylistOrder.stylist_id == actor.app_user_id)
    return [await order_details(session, o) for o in (await session.scalars(query)).all()]


@router.post("/orders")
async def create_order(
    command: NewOrderInput,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    order = await OrderService(session).create(
        command.customer_id, command.address_id, actor.app_user_id, actor.role == UserRole.ADMIN
    )
    await session.commit()
    return await order_details(session, order)


@router.get("/orders/{order_id}")
async def get_order(
    order_id: UUID,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    order = await OrderService(session).get(
        order_id, actor.app_user_id, actor.role == UserRole.ADMIN
    )
    return await order_details(session, order)


@router.post("/orders/{order_id}/items")
async def add_item(
    order_id: UUID,
    command: ItemInput,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    await OrderService(session).add_item(order_id, actor.app_user_id, **command.model_dump())
    await session.commit()
    return await order_details(
        session, await OrderService(session).get(order_id, actor.app_user_id)
    )


@router.post("/orders/{order_id}/quote")
async def quote_order(
    order_id: UUID,
    command: QuoteInput,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    order = await OrderService(session).get(order_id, actor.app_user_id)
    # A repeated request must not fetch a new rate for an already issued quote.
    if order.state == "AWAITING_PAYMENT":
        quote = await session.get(OrderQuote, order.active_quote_id)
        if quote.close_order != command.close_order:
            raise OrderError("Ожидается скриншот к текущему расчету")
    else:
        import httpx

        try:
            rate = await current_rate(session)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Не удалось получить курс ЦБ. Попробуйте позже") from exc
        await OrderService(session).issue_quote(
            order_id, actor.app_user_id, rate, command.close_order
        )
    await session.commit()
    return await order_details(session, order)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: UUID,
    command: CancelInput,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    await OrderService(session).cancel(
        order_id, actor.app_user_id, command.item_ids, command.reason
    )
    await session.commit()
    return await order_details(
        session, await OrderService(session).get(order_id, actor.app_user_id, True)
    )


@router.get("/orders/{order_id}/payments/{payment_id}/image")
async def payment_image(
    order_id: UUID,
    payment_id: UUID,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    await OrderService(session).get(order_id, actor.app_user_id, actor.role == UserRole.ADMIN)
    payment = await session.get(OrderPayment, payment_id)
    if payment is None or payment.order_id != order_id:
        raise HTTPException(404, "Скриншот не найден")
    path = Path(get_settings().payment_proof_dir) / payment.stored_filename
    if path.name != payment.stored_filename or not path.is_file():
        raise HTTPException(404, "Скриншот не найден")
    return FileResponse(path, media_type=payment.mime_type)


@router.post("/orders/{order_id}/refunds/{refund_id}/complete")
async def complete_refund(
    order_id: UUID,
    refund_id: UUID,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    order = await OrderService(session).get(order_id, actor.app_user_id, True)
    refund = await session.scalar(
        select(OrderRefund)
        .where(OrderRefund.id == refund_id, OrderRefund.order_id == order.id)
        .with_for_update()
    )
    if refund is None:
        raise OrderError("Возврат не найден")
    if refund.state != "REFUNDED":
        refund.state = "REFUNDED"
        item = await session.get(Item, refund.item_id)
        from app.models import ItemStatusHistory

        session.add(
            ItemStatusHistory(
                item_id=item.id,
                from_status=item.status,
                to_status=ItemStatus.RETURNED,
                changed_by_user_id=actor.app_user_id,
                reason="Возврат средств подтвержден администратором",
            )
        )
        item.status = ItemStatus.RETURNED
        OrderService(session).audit(
            actor.app_user_id, order, "REFUND_COMPLETED", {"refund_id": str(refund.id)}
        )
        from app.services.order_notifications import notify_order

        await notify_order(session, order, f"Возврат {refund.amount_rub} RUB выполнен.")
    await session.commit()
    return await order_details(session, order)


@router.put("/order-shipments/{shipment_id}/cost")
async def shipping_cost(
    shipment_id: UUID,
    command: ShippingCostInput,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    actor.require_admin()
    from app.models import AuditLog, CustomerShipment, ShipmentItem, ShipmentStatus

    shipment = await session.scalar(
        select(CustomerShipment).where(CustomerShipment.id == shipment_id).with_for_update()
    )
    if shipment is None or shipment.status not in (
        ShipmentStatus.SHIPPED,
        ShipmentStatus.DELIVERED,
    ):
        raise OrderError("Стоимость доставки можно указать после отправки")
    shipment.shipping_cost, shipment.currency = command.cost, command.currency
    session.add(
        AuditLog(
            actor_user_id=actor.app_user_id,
            action="SHIPPING_COST_SET",
            entity_type="SHIPMENT",
            entity_id=shipment.id,
            payload={"cost": str(command.cost), "currency": command.currency},
        )
    )
    orders = (
        await session.scalars(
            select(StylistOrder)
            .join(Item)
            .join(ShipmentItem)
            .where(ShipmentItem.shipment_id == shipment.id)
            .distinct()
        )
    ).all()
    from app.services.order_notifications import notify_order

    for order in orders:
        await notify_order(
            session, order, f"Доставка: {command.cost} {command.currency}, оплачивается отдельно."
        )
    await session.commit()
    return {"ok": True}


@router.post("/orders/{order_id}/recipient-invite")
async def recipient_invite(
    order_id: UUID,
    actor: RequestActor = Depends(get_request_actor),
    session: AsyncSession = Depends(get_session),
):
    order = await OrderService(session).get(
        order_id, actor.app_user_id, actor.role == UserRole.ADMIN
    )
    customer = await session.get(Customer, order.customer_id)
    from app.services.recipient_invites import create_invite

    if customer.app_user_id:
        return {"connected": True, "url": None}
    url = await create_invite(session, customer)
    await session.commit()
    return {"connected": False, "url": url}
