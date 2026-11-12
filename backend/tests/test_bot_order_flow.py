from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
        for invalid, valid in (
            ("123", "101000"),
            ("Московская область", "Moscow Oblast"),
            ("Москва", "Moscow"),
            ("Тестовая улица 1", "Test street 1"),
        ):
            step = conversation.data["recipient_step"]
            message.text = invalid
            await bot.receive_text(message, session, stylist, conversation)
            assert conversation.data["recipient_step"] == step
            message.text = valid
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


@pytest.mark.asyncio
async def test_admin_sees_and_opens_stylist_orders_without_editing_intake():
    from app.services.orders import OrderError

    async with SessionFactory() as session:
        _, stylist, admin, order, _, _, _ = await setup_order(session)
        other = SimpleNamespace(id=uuid4(), role=stylist.role)
        message = SimpleNamespace(answer=AsyncMock())
        await bot.list_orders(message, session, admin)
        buttons = message.answer.call_args.kwargs["reply_markup"].inline_keyboard
        assert any(button.callback_data == f"order:{order.id}" for row in buttons for button in row)
        conversation = SimpleNamespace(active_order_id=None, state="IDLE", data={})
        callback = SimpleNamespace(data=f"order:{order.id}", message=message, answer=AsyncMock())
        await bot.select_order(callback, session, admin, conversation)
        assert order.number in message.answer.call_args.args[0]
        assert conversation.active_order_id is None
        await bot.list_orders(message, session, other)
        assert message.answer.call_args.args[0] == "Сохраненных заказов пока нет."
        with pytest.raises(OrderError):
            await bot.select_order(callback, session, other, conversation)
        await session.rollback()


@pytest.mark.asyncio
async def test_application_uses_authenticated_inline_launch_and_repairs_chat_menu(monkeypatch):
    monkeypatch.setattr(
        bot, "get_settings", lambda: SimpleNamespace(telegram_webapp_url="https://example.test")
    )
    reply_buttons = [button for row in bot.keyboard().keyboard for button in row]
    opener = next(button for button in reply_buttons if button.text == "Открыть приложение")
    assert opener.web_app is None  # Reply-keyboard web apps receive no signed initData.
    message = SimpleNamespace(
        answer=AsyncMock(),
        bot=SimpleNamespace(set_chat_menu_button=AsyncMock()),
        chat=SimpleNamespace(id=252246696),
    )
    await bot.start(message, SimpleNamespace(state="IDLE"))
    menu = message.bot.set_chat_menu_button.call_args.kwargs
    assert (
        menu["chat_id"] == 252246696 and menu["menu_button"].web_app.url == "https://example.test"
    )
    launch = message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert launch.web_app.url == "https://example.test"


@pytest.mark.asyncio
async def test_recipient_form_started_before_update_requests_invalid_field_again():
    from bot.app.recipient_form import accept_recipient_value

    conversation = SimpleNamespace(
        state="RECIPIENT",
        data={
            "recipient_step": 6,
            "recipient_values": dict(
                recipient_name="TEST RECIPIENT",
                phone="+79990000000",
                telegram_username=None,
                postal_code="101000",
                region="Московская область",
                city="Moscow",
            ),
        },
    )
    message = SimpleNamespace(answer=AsyncMock())
    assert await accept_recipient_value(message, None, None, conversation, "Test Street 1") is None
    assert conversation.data["recipient_step"] == 4
    assert conversation.data["recipient_values"]["address_line1"] == "Test Street 1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "automatic,entered,source",
    [(True, "35,95", "zara_browser"), (True, "36", "manual"), (False, "35,95", "manual")],
)
async def test_bot_suggested_price_and_manual_fallback_are_saved(
    monkeypatch, automatic, entered, source
):
    from decimal import Decimal

    from sqlalchemy import select

    from app.models import Item

    async with SessionFactory() as session:
        _, stylist, _, order, _, _, _ = await setup_order(session)
        url = "https://www.zara.com/es/en/combined-satin-trousers-p08912573.html"
        order.intake_snapshot = {"urls": [url]}
        conversation = SimpleNamespace(active_order_id=order.id, state="IDLE", data={})
        result = ImportResult(
            identify_product(url),
            name="Trousers",
            price_eur=Decimal("35.95") if automatic else None,
            manual_reason=None if automatic else "browser_unavailable",
            source="zara_browser",
        )
        monkeypatch.setattr(bot, "import_product", AsyncMock(return_value=result))
        message = SimpleNamespace(text="", answer=AsyncMock())
        await bot.prompt_pending(message, order, conversation)
        prompt = message.answer.call_args.args[0]
        assert ("35.95 EUR" in prompt) if automatic else ("Введите цену вручную" in prompt)
        message.text = f"{entered}; M; Black; 1"
        await bot.receive_text(message, session, stylist, conversation)
        item = await session.scalar(select(Item).where(Item.order_id == order.id))
        assert item.listed_price == Decimal(entered.replace(",", "."))
        assert item.price_source == source
        assert conversation.state == "IDLE" and order.intake_snapshot["urls"] == []
        await session.rollback()
