import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bot.app import item_form
from bot.app import main as bot
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models import BotConversation, Item
from app.services.product_import import (
    ImportResult,
    identify_product,
    validate_variants,
    zara_variants,
)
from test_stylist_orders import setup_order

URL = "https://www.zara.com/es/en/basic-plush-trousers-p03199635.html?v1=1&v2=42"
VARIANTS = [
    {
        "name": "Black",
        "url": URL,
        "price_eur": "19.95",
        "sizes": [
            {"name": "XS", "price_eur": "19.95"},
            {"name": "M", "price_eur": "19.95"},
        ],
    },
    {
        "name": "Blue",
        "url": URL.replace("v1=1", "v1=2"),
        "price_eur": "25.95",
        "sizes": [
            {"name": "38", "price_eur": "25.95"},
            {"name": "40", "price_eur": "29.95"},
        ],
    },
]


def test_primary_zara_payload_filters_stock_and_keeps_color_sizes():
    payload = {
        "product": {
            "seo": {"seoProductId": "03199635"},
            "detail": {
                "colors": [
                    {
                        "name": "Black",
                        "productId": 123,
                        "price": 1995,
                        "sizes": [
                            {"name": "XS", "availability": "in_stock", "price": 1995},
                            {
                                "name": "S",
                                "availability": "out_of_stock",
                                "price": 1995,
                            },
                            {"name": "M", "availability": "coming_soon", "price": 1995},
                        ],
                    },
                    {
                        "name": "Blue",
                        "productId": 456,
                        "price": 2995,
                        "sizes": [
                            {"name": "38", "availability": "in_stock", "price": 2995}
                        ],
                    },
                ]
            },
        }
    }
    html = "<script>window.zara.viewPayload = " + json.dumps(payload) + ";</script>"
    result = zara_variants(html, identify_product(URL))
    assert [c["name"] for c in result] == ["Black", "Blue"]
    assert result[0]["sizes"] == [{"name": "XS", "price_eur": "19.95"}]
    assert result[1]["sizes"][0]["name"] == "38"
    assert "v1=456" in result[1]["url"] and "v2=42" in result[1]["url"]
    assert (
        zara_variants(html.replace("03199635", "99999999"), identify_product(URL)) == ()
    )
    assert (
        zara_variants(
            "<script>window.zara.viewPayload = evil();</script>", identify_product(URL)
        )
        == ()
    )


def test_variant_client_rejects_untrusted_urls_oversized_and_invalid_prices():
    product = identify_product(URL)
    assert (
        validate_variants([{**VARIANTS[0], "url": "https://evil.test"}], product) == ()
    )
    assert (
        validate_variants(
            [{**VARIANTS[0], "url": URL.replace("03199635", "99999999")}], product
        )
        == ()
    )
    assert validate_variants(VARIANTS * 26, product) == ()
    valid = validate_variants([{**VARIANTS[0], "price_eur": "NaN"}], product)
    assert valid[0]["price_eur"] is None


async def press(message, session, actor, conversation, action):
    callback = SimpleNamespace(
        message=message,
        answer=AsyncMock(),
        data=f"item_option:{conversation.data['option_token']}:{action}",
    )
    await bot.choose_item_option(callback, session, actor, conversation)
    return callback


@pytest.mark.asyncio
async def test_color_size_reprice_back_restart_quantity_and_duplicate_save(monkeypatch):
    async with SessionFactory() as session:
        _, actor, _, order, _, _, _ = await setup_order(session)
        conversation = BotConversation(
            telegram_user_id=actor.telegram_user_id,
            active_order_id=order.id,
            state="IDLE",
            data={},
        )
        session.add(conversation)
        order.intake_snapshot = {"urls": [URL]}
        result = ImportResult(
            identify_product(URL),
            name="Trousers",
            price_eur=Decimal("19.95"),
            source="zara_browser",
            variants=tuple(VARIANTS),
        )
        monkeypatch.setattr(bot, "import_product", AsyncMock(return_value=result))
        message = SimpleNamespace(text="", answer=AsyncMock())
        await bot.prompt_pending(message, order, conversation)
        callback = SimpleNamespace(
            data=f"item_price:{conversation.data['price_token']}:yes",
            message=message,
            answer=AsyncMock(),
        )
        await bot.confirm_item_price(callback, session, actor, conversation)
        assert conversation.data["item_step"] == "color"
        old = await press(message, session, actor, conversation, "color_1")
        assert conversation.data["color"] == "Blue"
        assert [
            b.text
            for row in message.answer.call_args.kwargs["reply_markup"].inline_keyboard
            for b in row
        ][:2] == ["38", "40"]
        await bot.choose_item_option(old, session, actor, conversation)
        assert conversation.data["item_step"] == "size"
        await press(message, session, actor, conversation, "size_1")
        assert conversation.data["item_step"] == "reprice"
        assert conversation.data["suggested_price"] == "19.95"
        await press(message, session, actor, conversation, "yes")
        assert conversation.data["suggested_price"] == "29.95"
        await press(message, session, actor, conversation, "back")
        assert conversation.data["item_step"] == "size"
        await press(message, session, actor, conversation, "size_0")
        await press(message, session, actor, conversation, "yes")
        await session.flush()
        session.expire(conversation)
        await session.refresh(conversation)
        assert conversation.data["item_step"] == "quantity"
        final = await press(message, session, actor, conversation, "qty_2")
        item = await session.scalar(select(Item).where(Item.order_id == order.id))
        assert (item.color, item.size, item.quantity, item.listed_price) == (
            "Blue",
            "38",
            2,
            Decimal("25.95"),
        )
        assert "v1=2" in item.product_url
        await bot.choose_item_option(final, session, actor, conversation)
        assert (
            len(
                (
                    await session.scalars(select(Item).where(Item.order_id == order.id))
                ).all()
            )
            == 1
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_one_color_auto_selection_manual_choices_and_quantity_validation():
    from app.services.orders import OrderError

    message = SimpleNamespace(answer=AsyncMock())
    conversation = SimpleNamespace(
        data={
            "url": URL,
            "variants": VARIANTS[:1],
            "suggested_price": "19.95",
            "price_source": "zara_browser",
        }
    )
    await item_form.begin_options(message, conversation)
    assert (
        conversation.data["color"] == "Black"
        and conversation.data["item_step"] == "size"
    )
    await item_form.accept_action(message, conversation, "manual")
    await item_form.accept_text(message, conversation, "XXL")
    await item_form.accept_action(message, conversation, "manual")
    with pytest.raises(OrderError):
        await item_form.accept_text(message, conversation, "0")
    command = await item_form.accept_text(message, conversation, "4")
    assert command.size == "XXL" and command.color == "Black" and command.quantity == 4


@pytest.mark.asyncio
async def test_no_metadata_manual_color_size_and_back_to_price():
    message = SimpleNamespace(answer=AsyncMock())
    conversation = SimpleNamespace(
        data={
            "url": URL,
            "variants": [],
            "suggested_price": "19.95",
            "price_source": "manual",
        }
    )
    await item_form.begin_options(message, conversation)
    await item_form.accept_action(message, conversation, "back")
    assert conversation.data["item_step"] == "price"
    await item_form.accept_action(message, conversation, "yes")
    await item_form.accept_action(message, conversation, "skip")
    await item_form.accept_text(message, conversation, "42")
    command = await item_form.accept_action(message, conversation, "qty_1")
    assert command.color == "-" and command.size == "42" and command.quantity == 1


def test_saved_zara_page_snapshot():
    from pathlib import Path

    payload = (
        Path(__file__).with_name("fixtures").joinpath("zara-options.json").read_text()
    )
    result = zara_variants(
        "<script>window.zara.viewPayload = " + payload + ";</script>",
        identify_product(URL),
    )
    assert [v["name"] for v in result] == ["Sand / Marl", "Navy blue", "Grey marl"]
    assert all([s["name"] for s in c["sizes"]] == ["S", "M", "L", "XL"] for c in result)


@pytest.mark.asyncio
async def test_manual_override_after_variant_price_change():
    message = SimpleNamespace(answer=AsyncMock())
    conversation = SimpleNamespace(
        data={
            "url": URL,
            "variants": VARIANTS,
            "suggested_price": "19.95",
            "price_source": "zara_browser",
        }
    )
    await item_form.begin_options(message, conversation)
    await item_form.accept_action(message, conversation, "color_1")
    await item_form.accept_action(message, conversation, "size_0")
    await item_form.accept_action(message, conversation, "edit")
    await item_form.accept_text(message, conversation, "24,95")
    command = await item_form.accept_action(message, conversation, "qty_3")
    assert (
        command.price == Decimal("24.95")
        and conversation.data["price_source"] == "manual"
    )
    assert command.color == "Blue" and command.size == "38"


@pytest.mark.asyncio
async def test_browser_client_passes_valid_options_but_ignores_bad_options(monkeypatch):
    import httpx
    from app.services.product_import import import_from_browser

    factory = httpx.AsyncClient
    payload = {"product_id": "03199635", "price_eur": "19.95", "variants": VARIANTS}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: factory(transport=transport, **kwargs)
    )
    result = await import_from_browser(identify_product(URL), "http://browser:8080")
    assert result.variants[1]["sizes"][0]["name"] == "38"
    payload["variants"] = "invalid"
    result = await import_from_browser(identify_product(URL), "http://browser:8080")
    assert result.variants == () and result.price_eur == Decimal("19.95")


@pytest.mark.asyncio
async def test_missing_variant_price_requires_manual_entry_and_back_works():
    message = SimpleNamespace(answer=AsyncMock())
    unknown = {'name': 'Black', 'url': URL, 'price_eur': None,
               'sizes': [{'name': 'M', 'price_eur': None}]}
    conversation = SimpleNamespace(data={
        'url': URL, 'variants': [unknown], 'suggested_price': '19.95', 'price_source': 'zara_browser',
    })
    await item_form.begin_options(message, conversation)
    await item_form.accept_action(message, conversation, 'size_0')
    assert conversation.data['item_step'] == 'price_manual'
    await item_form.accept_action(message, conversation, 'back')
    assert conversation.data['item_step'] == 'size'
    await item_form.accept_action(message, conversation, 'size_0')
    await item_form.accept_text(message, conversation, '18,95')
    command = await item_form.accept_action(message, conversation, 'qty_1')
    assert command.price == Decimal('18.95')
