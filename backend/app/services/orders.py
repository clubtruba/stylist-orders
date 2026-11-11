from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.money import allocate_proportional
from app.models import (
    AuditLog,
    Customer,
    CustomerAddress,
    ExchangeRate,
    Item,
    ItemStatus,
    OrderPayment,
    OrderQuote,
    OrderRefund,
    QuoteLine,
    StylistOrder,
)
from app.pricing import calculate_quote
from app.services.rates import moscow_today


class OrderError(ValueError):
    pass


class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, order_id: UUID, actor_id: UUID, admin: bool = False) -> StylistOrder:
        order = await self.session.scalar(
            select(StylistOrder).where(StylistOrder.id == order_id).with_for_update()
        )
        if order is None or (not admin and order.stylist_id != actor_id):
            raise OrderError("Заказ не найден или недоступен")
        return order

    def audit(self, actor: UUID, order: StylistOrder, action: str, payload: dict | None = None):
        self.session.add(
            AuditLog(
                actor_user_id=actor,
                action=action,
                entity_type="ORDER",
                entity_id=order.id,
                payload=payload or {},
            )
        )

    async def create(
        self, customer_id: UUID, address_id: UUID, actor: UUID, admin=False
    ) -> StylistOrder:
        customer = await self.session.get(Customer, customer_id)
        address = await self.session.get(CustomerAddress, address_id)
        if customer is None or (not admin and customer.stylist_id != actor):
            raise OrderError("Получатель недоступен")
        if address is None or address.customer_id != customer_id or address.country_code != "RU":
            raise OrderError("Выберите адрес получателя в России")
        snapshot = {
            key: getattr(address, key)
            for key in (
                "recipient_name",
                "phone",
                "country_code",
                "postal_code",
                "region",
                "city",
                "address_line1",
                "address_line2",
            )
        }
        snapshot["telegram_username"] = customer.telegram_username
        order = StylistOrder(
            number="SO-" + uuid4().hex[:12].upper(),
            stylist_id=actor,
            customer_id=customer_id,
            address_snapshot=snapshot,
            state="DRAFT",
        )
        self.session.add(order)
        await self.session.flush()
        self.audit(actor, order, "ORDER_CREATED")
        return order

    async def add_item(
        self,
        order_id: UUID,
        actor: UUID,
        *,
        url: str,
        price: Decimal,
        size: str,
        color: str,
        quantity: int,
        name: str | None = None,
        source="manual",
    ) -> Item:
        order = await self.get(order_id, actor)
        if order.state != "DRAFT":
            raise OrderError("Добавление доступно только в черновик без ожидающего оплаты расчета")
        if (
            not price.is_finite()
            or price <= 0
            or price != price.quantize(Decimal(".01"))
            or not 1 <= quantity <= 100
        ):
            raise OrderError(
                "Укажите положительную цену с точностью до цента и количество от 1 до 100"
            )
        if price * quantity > Decimal("10000000"):
            raise OrderError("Стоимость позиции слишком велика")
        from app.services.product_import import identify_product

        identify_product(url)
        item = Item(
            order_id=order.id,
            customer_id=order.customer_id,
            product_url=url,
            product_name=name,
            size=size,
            color=color,
            quantity=quantity,
            listed_price=price,
            listed_currency="EUR",
            status=ItemStatus.TO_BUY,
            price_source=source,
        )
        self.session.add(item)
        await self.session.flush()
        self.audit(actor, order, "ORDER_ITEM_ADDED", {"item_id": str(item.id)})
        return item

    async def issue_quote(
        self, order_id: UUID, actor: UUID, rate: ExchangeRate, close_order: bool
    ) -> OrderQuote | None:
        order = await self.get(order_id, actor)
        if order.state == "AWAITING_PAYMENT":
            existing = await self.session.get(OrderQuote, order.active_quote_id)
            if existing and existing.close_order == close_order:
                return existing
            raise OrderError("Сначала прикрепите скриншот к текущему расчету")
        if order.state != "DRAFT":
            raise OrderError("Формирование заказа уже завершено")
        if (order.intake_snapshot or {}).get("urls"):
            raise OrderError("Сначала заполните параметры всех присланных товаров в боте")
        items = list(
            (await self.session.scalars(select(Item).where(Item.order_id == order.id))).all()
        )
        active = [
            item
            for item in items
            if item.status
            not in (ItemStatus.CANCELLED, ItemStatus.RETURNED, ItemStatus.RETURN_IN_PROGRESS)
        ]
        if not active:
            raise OrderError("В заказе нет активных товаров")
        paid_items = set(
            (
                await self.session.scalars(
                    select(QuoteLine.item_id)
                    .join(OrderQuote)
                    .where(OrderQuote.order_id == order.id, OrderQuote.state == "PAID")
                )
            ).all()
        )
        unpaid = [item for item in active if item.id not in paid_items]
        if not unpaid:
            if close_order:
                order.state = "SUBMITTED"
                self.audit(actor, order, "ORDER_SUBMITTED")
                return None
            raise OrderError("Все добавленные товары уже оплачены")
        if rate.business_date != moscow_today():
            raise OrderError("Нужен курс на текущую московскую дату")
        values = {str(item.id): item.listed_price * item.quantity for item in unpaid}
        calculation = calculate_quote(
            sum(values.values()), rate.eur_rub, rate.business_date, moscow_today()
        )
        quote = OrderQuote(
            order_id=order.id,
            rate_date=rate.business_date,
            eur_rub_rate=rate.eur_rub,
            goods_eur=calculation.goods_eur,
            total_eur=calculation.total_eur,
            due_rub=calculation.total_rub,
            close_order=close_order,
            state="ISSUED",
        )
        self.session.add(quote)
        await self.session.flush()
        allocated = allocate_proportional(quote.due_rub, values)
        for item in unpaid:
            self.session.add(
                QuoteLine(
                    quote_id=quote.id,
                    item_id=item.id,
                    snapshot={
                        "price_eur": str(item.listed_price),
                        "quantity": item.quantity,
                        "size": item.size,
                        "color": item.color,
                        "url": item.product_url,
                        "name": item.product_name,
                        "commission": "0.20",
                        "rub_markup": "0.05",
                    },
                    amount_rub=allocated[str(item.id)],
                )
            )
        order.active_quote_id = quote.id
        order.state = "AWAITING_PAYMENT"
        self.audit(actor, order, "QUOTE_ISSUED", {"quote_id": str(quote.id)})
        return quote

    async def confirm_payment(
        self,
        order_id: UUID,
        quote_id: UUID,
        actor: UUID,
        *,
        file_id: str,
        stored_filename: str,
        mime_type: str,
        chat_id: int,
        message_id: int,
        paid_at: datetime,
    ) -> OrderPayment:
        order = await self.get(order_id, actor)
        existing = await self.session.scalar(
            select(OrderPayment).where(OrderPayment.quote_id == quote_id)
        )
        if existing:
            if existing.telegram_chat_id == chat_id and existing.telegram_message_id == message_id:
                return existing
            raise OrderError("К этому расчету уже прикреплен платеж")
        if order.state != "AWAITING_PAYMENT" or order.active_quote_id != quote_id:
            raise OrderError("Этот расчет не ожидает оплаты")
        quote = await self.session.get(OrderQuote, quote_id)
        if quote is None or quote.order_id != order.id or quote.state != "ISSUED":
            raise OrderError("Расчет недоступен")
        if not file_id or not stored_filename or paid_at.utcoffset() is None:
            raise OrderError("Нужны сохраненный скриншот и дата оплаты")
        duplicate = await self.session.scalar(
            select(OrderPayment).where(
                OrderPayment.telegram_chat_id == chat_id,
                OrderPayment.telegram_message_id == message_id,
            )
        )
        if duplicate:
            raise OrderError("Это сообщение уже использовано для другого расчета")
        payment = OrderPayment(
            order_id=order.id,
            quote_id=quote.id,
            screenshot_file_id=file_id,
            stored_filename=stored_filename,
            mime_type=mime_type,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            paid_at=paid_at,
            amount_rub=quote.due_rub,
        )
        self.session.add(payment)
        quote.state = "PAID"
        order.state = "SUBMITTED" if quote.close_order else "DRAFT"
        order.active_quote_id = None
        self.audit(
            actor,
            order,
            "PAYMENT_ATTACHED",
            {"quote_id": str(quote.id), "amount_rub": str(quote.due_rub)},
        )
        await self.session.flush()
        return payment

    async def cancel(
        self, order_id: UUID, actor: UUID, item_ids: list[UUID] | None, reason: str
    ) -> list[OrderRefund]:
        order = await self.get(order_id, actor, admin=True)
        if not reason.strip():
            raise OrderError("Укажите причину отмены или возврата")
        items = list(
            (await self.session.scalars(select(Item).where(Item.order_id == order.id))).all()
        )
        selected = items if item_ids is None else [item for item in items if item.id in item_ids]
        if not selected or (item_ids is not None and {i.id for i in selected} != set(item_ids)):
            raise OrderError("Позиции не найдены в этом заказе")
        if order.active_quote_id:
            quote = await self.session.get(OrderQuote, order.active_quote_id)
            if quote and quote.state == "ISSUED":
                quote.state = "VOID"
                order.active_quote_id = None
                order.state = "DRAFT"
        refunds = []
        for item in selected:
            existing = await self.session.scalar(
                select(OrderRefund).where(OrderRefund.item_id == item.id)
            )
            if existing:
                refunds.append(existing)
                continue
            line = await self.session.scalar(
                select(QuoteLine)
                .join(OrderQuote)
                .where(QuoteLine.item_id == item.id, OrderQuote.state == "PAID")
            )
            target = ItemStatus.RETURN_IN_PROGRESS if line else ItemStatus.CANCELLED
            previous = item.status
            item.status = target
            from app.models import ItemStatusHistory

            self.session.add(
                ItemStatusHistory(
                    item_id=item.id,
                    from_status=previous,
                    to_status=target,
                    changed_by_user_id=actor,
                    reason=reason,
                )
            )
            if line:
                refund = OrderRefund(
                    order_id=order.id,
                    item_id=item.id,
                    amount_rub=line.amount_rub,
                    reason=reason,
                    state="PENDING",
                )
                self.session.add(refund)
                refunds.append(refund)
        if all(
            item.status
            in (ItemStatus.CANCELLED, ItemStatus.RETURN_IN_PROGRESS, ItemStatus.RETURNED)
            for item in items
        ):
            order.state = "CANCELLED"
        self.audit(
            actor,
            order,
            "ORDER_ITEMS_CANCELLED",
            {"items": [str(i.id) for i in selected], "reason": reason},
        )
        from app.services.order_notifications import notify_order

        await notify_order(
            self.session,
            order,
            f"Отмена/возврат позиций. Причина: {reason}. Сумма возврата: {sum((r.amount_rub for r in refunds), Decimal(0))} RUB.",
        )
        await self.session.flush()
        return refunds
