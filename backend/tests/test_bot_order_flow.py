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
