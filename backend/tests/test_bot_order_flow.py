from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bot.app import main as bot
from test_stylist_orders import setup_order

from app.db.session import SessionFactory
from app.models import BotConversation
from app.services.product_import import ImportResult, identify_product


@pytest.mark.asyncio
async def test_link_queue_survives_pause_switch_and_resume(monkeypatch):
    async with SessionFactory() as session:
        _, stylist, _, order, _, _, _ = await setup_order(session)
        conversation = BotConversation(
            telegram_user_id=stylist.telegram_user_id,
            state="IDLE",
            data={},
            active_order_id=order.id,
        )
        session.add(conversation)
        await session.flush()

        async def imported(url):
            return ImportResult(identify_product(url), manual_reason="http_403")

        monkeypatch.setattr(bot, "import_product", imported)
        first = "https://www2.hm.com/es_es/productpage.1352121001.html"
        second = "https://www2.hm.com/es_es/productpage.1357440002.html"
        message = SimpleNamespace(text=f"{first}\n{second}", answer=AsyncMock())
        await bot.receive_text(message, session, stylist, conversation)
        assert order.intake_snapshot["urls"] == [first, second]
        assert conversation.state == "ITEM"
        await bot.pause(message, conversation)
        assert conversation.active_order_id is None and order.intake_snapshot["urls"] == [
            first,
            second,
        ]
        callback = SimpleNamespace(data=f"order:{order.id}", message=message, answer=AsyncMock())
        await bot.select_order(callback, session, stylist, conversation)
        assert conversation.data["url"] == first
        message.text = "29,99; M; черный; 2"
        await bot.receive_text(message, session, stylist, conversation)
        assert order.intake_snapshot["urls"] == [second]
        assert conversation.data["url"] == second
        message.text = "10; L; белый; 1"
        await bot.receive_text(message, session, stylist, conversation)
        assert not order.intake_snapshot["urls"] and conversation.state == "IDLE"
        await session.rollback()


@pytest.mark.asyncio
async def test_recipient_wizard_skip_validation_back_and_persistence():
    from bot.app.recipient_form import begin_recipient_form

    from app.models import Customer, StylistOrder

    async with SessionFactory() as session:
        _, stylist, _, old_order, _, _, _ = await setup_order(session)
        conversation = BotConversation(
            telegram_user_id=stylist.telegram_user_id,
            state="IDLE",
            data={},
            active_order_id=old_order.id,
        )
        session.add(conversation)
        await session.flush()
        begin_recipient_form(conversation)
        message = SimpleNamespace(text="Иван Иванов", answer=AsyncMock())
        await bot.receive_text(message, session, stylist, conversation)
        assert conversation.data["recipient_step"] == 0
        for answer in ("TEST RECIPIENT", "+7 (999) 000-00-00"):
            message.text = answer
            await bot.receive_text(message, session, stylist, conversation)
        assert conversation.data["recipient_step"] == 2
        await session.flush()
        session.expire(conversation)
        await session.refresh(conversation)
        assert conversation.data["recipient_values"]["recipient_name"] == "TEST RECIPIENT"
        callback = SimpleNamespace(
            data="recipient_form:back:2", message=message, answer=AsyncMock()
        )
        await bot.recipient_navigation(callback, session, stylist, conversation)
        assert conversation.data["recipient_step"] == 1
        message.text = "+79990000001"
        await bot.receive_text(message, session, stylist, conversation)
        callback.data = "recipient_form:skip:2"
        await bot.recipient_navigation(callback, session, stylist, conversation)
        assert conversation.data["recipient_step"] == 3
        assert conversation.data["recipient_values"]["telegram_username"] is None
        # A second click on the previous skip button cannot skip the postcode.
        await bot.recipient_navigation(callback, session, stylist, conversation)
        assert conversation.data["recipient_step"] == 3
        message.text = "123"
        await bot.receive_text(message, session, stylist, conversation)
        assert conversation.data["recipient_step"] == 3
        for answer in ("101000", "Московская область", "Москва", "Тестовая улица, дом 1"):
            message.text = answer
            await bot.receive_text(message, session, stylist, conversation)
        assert conversation.state == "IDLE"
        assert conversation.active_order_id != old_order.id
        order = await session.get(StylistOrder, conversation.active_order_id)
        customer = await session.get(Customer, order.customer_id)
        assert customer.telegram_username is None
        assert customer.phone == "+79990000001"
        assert order.address_snapshot["telegram_username"] is None
        await session.rollback()


@pytest.mark.asyncio
async def test_recipient_wizard_cancel_keeps_existing_orders():
    from bot.app.recipient_form import begin_recipient_form

    async with SessionFactory() as session:
        service, stylist, _, order, _, _, _ = await setup_order(session)
        conversation = BotConversation(
            telegram_user_id=stylist.telegram_user_id,
            state="IDLE",
            data={},
            active_order_id=order.id,
        )
        begin_recipient_form(conversation)
        message = SimpleNamespace(text="TEST RECIPIENT", answer=AsyncMock())
        await bot.receive_text(message, session, stylist, conversation)
        callback = SimpleNamespace(
            data="recipient_form:cancel:1", message=message, answer=AsyncMock()
        )
        await bot.recipient_navigation(callback, session, stylist, conversation)
        assert conversation.state == "IDLE" and conversation.data == {}
        assert (await service.get(order.id, stylist.id)).id == order.id
        await session.rollback()
