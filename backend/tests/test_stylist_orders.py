from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.db.session import SessionFactory
from app.models import AppUser, Customer, CustomerAddress, ExchangeRate, OrderPayment, UserRole
from app.services.orders import OrderError, OrderService
from app.services.rates import moscow_today, parse_cbr


async def setup_order(session):
    stylist = AppUser(
        telegram_user_id=uuid4().int % 10**14, first_name="Stylist", role=UserRole.CUSTOMER
    )
    admin = AppUser(telegram_user_id=uuid4().int % 10**14, first_name="Admin", role=UserRole.ADMIN)
    session.add_all([stylist, admin])
    await session.flush()
    customer = Customer(stylist_id=stylist.id, display_name="IVAN IVANOV", phone="+79990000000")
    session.add(customer)
    await session.flush()
    address = CustomerAddress(
        customer_id=customer.id,
        label="Home",
        recipient_name=customer.display_name,
        phone=customer.phone,
        country_code="RU",
        postal_code="101000",
        city="Moscow",
        address_line1="Test street 1",
        is_default=True,
    )
    session.add(address)
    await session.flush()
    service = OrderService(session)
    order = await service.create(customer.id, address.id, stylist.id)
    rate = ExchangeRate(
        business_date=moscow_today(), effective_date=moscow_today(), eur_rub=D("95")
    )
    return service, stylist, admin, order, rate, customer, address


async def add(service, order, stylist, price="100"):
    return await service.add_item(
        order.id,
        stylist.id,
        url="https://www2.hm.com/es_es/productpage.1352121001.html",
        price=D(price),
        size="M",
        color="black",
        quantity=1,
    )


async def pay(service, order, quote, stylist, message=1):
    return await service.confirm_payment(
        order.id,
        quote.id,
        stylist.id,
        file_id="file-id",
        stored_filename=f"{uuid4()}.jpg",
        mime_type="image/jpeg",
        chat_id=stylist.telegram_user_id,
        message_id=message,
        paid_at=datetime.now(timezone.utc) + timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_payment_supplement_and_refund_preserve_original_amounts():
    async with SessionFactory() as session:
        service, stylist, admin, order, rate, _, _ = await setup_order(session)
        first = await add(service, order, stylist)
        quote = await service.issue_quote(order.id, stylist.id, rate, False)
        assert quote.due_rub == D("11970")
        assert (await service.issue_quote(order.id, stylist.id, rate, False)).id == quote.id
        payment = await pay(service, order, quote, stylist)
        assert payment.amount_rub == D("11970") and order.state == "DRAFT"
        replay = await service.confirm_payment(
            order.id,
            quote.id,
            stylist.id,
            file_id="file-id",
            stored_filename="unused.jpg",
            mime_type="image/jpeg",
            chat_id=stylist.telegram_user_id,
            message_id=1,
            paid_at=datetime.now(timezone.utc),
        )
        assert replay.id == payment.id
        assert (
            await session.scalar(
                select(func.count(OrderPayment.id)).where(OrderPayment.order_id == order.id)
            )
            == 1
        )
        await add(service, order, stylist, "50")
        rate.eur_rub = D("100")
        second = await service.issue_quote(order.id, stylist.id, rate, True)
        assert second.due_rub == D("6300")
        await pay(service, order, second, stylist, message=2)
        assert order.state == "SUBMITTED"
        with pytest.raises(OrderError):
            await add(service, order, stylist)
        refunds = await service.cancel(order.id, admin.id, [first.id], "Размер отсутствует")
        assert refunds[0].amount_rub == D("11970") and order.state == "SUBMITTED"
        assert (await service.cancel(order.id, admin.id, [first.id], "Повтор"))[0].id == refunds[
            0
        ].id
        await session.rollback()


@pytest.mark.asyncio
async def test_parallel_drafts_address_snapshot_and_access():
    async with SessionFactory() as session:
        service, stylist, admin, order, _, customer, address = await setup_order(session)
        second = await service.create(customer.id, address.id, stylist.id)
        assert second.id != order.id and second.number != order.number
        address.address_line1 = "Changed address"
        assert order.address_snapshot["address_line1"] == "Test street 1"
        with pytest.raises(OrderError):
            await service.get(order.id, admin.id)
        with pytest.raises(OrderError):
            await service.create(customer.id, address.id, admin.id)
        await session.rollback()


@pytest.mark.asyncio
async def test_cancel_unpaid_quote_and_close_paid_order():
    async with SessionFactory() as session:
        service, stylist, admin, order, rate, _, _ = await setup_order(session)
        item = await add(service, order, stylist)
        quote = await service.issue_quote(order.id, stylist.id, rate, False)
        assert not await service.cancel(order.id, admin.id, [item.id], "Нет товара")
        assert quote.state == "VOID" and order.state == "CANCELLED"
        with pytest.raises(OrderError):
            await pay(service, order, quote, stylist)
        await session.rollback()
    async with SessionFactory() as session:
        service, stylist, _, order, rate, _, _ = await setup_order(session)
        await add(service, order, stylist)
        quote = await service.issue_quote(order.id, stylist.id, rate, False)
        await pay(service, order, quote, stylist)
        assert await service.issue_quote(order.id, stylist.id, rate, True) is None
        assert order.state == "SUBMITTED"
        await session.rollback()


def test_cbr_weekend_effective_date_and_nominal():
    effective, rate = parse_cbr(
        b'<ValCurs Date="07.11.2026"><Valute><CharCode>EUR</CharCode><Nominal>10</Nominal><Value>950,1250</Value></Valute></ValCurs>',
        moscow_today().replace(day=8),
    )
    assert effective.day == 7 and rate == D("95.0125")
    with pytest.raises(ValueError):
        parse_cbr(b'<ValCurs Date="12.11.2026"/>', moscow_today().replace(day=8))
