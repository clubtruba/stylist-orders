"""Persisted product choices; callback tokens change after every step."""

from decimal import Decimal
from uuid import uuid4

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pydantic import ValidationError

from app.schemas.orders import ItemInput
from app.services.orders import OrderError


def markup(token, choices, columns=2, extra=()):
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"item_option:{token}:{action}")
        for label, action in choices
    ]
    rows = [buttons[i : i + columns] for i in range(0, len(buttons), columns)]
    rows += [
        [
            InlineKeyboardButton(
                text=label, callback_data=f"item_option:{token}:{action}"
            )
        ]
        for label, action in extra
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def selected_variant(data):
    index = data.get("selected_variant")
    variants = data.get("variants", [])
    return (
        variants[index]
        if isinstance(index, int) and 0 <= index < len(variants)
        else None
    )


def set_color(data, index):
    variant = data["variants"][index]
    return {
        **data,
        "selected_variant": index,
        "color": variant["name"],
        "selected_url": variant["url"],
        "size": None,
        "option_price": None,
    }


async def show_step(message, conversation, step):
    data = conversation.data
    token = uuid4().hex[:12]
    conversation.data = {
        **data,
        "price_step": "wizard",
        "item_step": step,
        "option_token": token,
    }
    back = [("Назад", "back")]
    if step == "color":
        variants = data.get("variants", [])
        choices = [(v["name"], f"color_{i}") for i, v in enumerate(variants)]
        text = "Выберите цвет:"
        if not choices:
            text = "Цвета с сайта не получены. Напишите цвет или нажмите «Без выбора цвета»."
        await message.answer(
            text,
            reply_markup=markup(
                token,
                choices,
                extra=[
                    ("Ввести вручную", "manual"),
                    ("Без выбора цвета", "skip"),
                    *back,
                ],
            ),
        )
    elif step == "size":
        variant = selected_variant(data)
        sizes = variant["sizes"] if variant else []
        text = f"Цвет: {data['color']}. Выберите размер:\nПо наличию на момент проверки сайта."
        if not sizes:
            text = f"Цвет: {data['color']}. Размеры не получены или нет размеров в наличии. Введите размер вручную."
        await message.answer(
            text,
            reply_markup=markup(
                token,
                [(s["name"], f"size_{i}") for i, s in enumerate(sizes)],
                columns=4,
                extra=[("Ввести вручную", "manual"), *back],
            ),
        )
    elif step in ("color_manual", "size_manual", "quantity_manual", "price_manual"):
        prompts = {
            "color_manual": "Введите цвет одним сообщением или отправьте - без выбора цвета.",
            "size_manual": "Введите размер одним сообщением, например M или 38.",
            "quantity_manual": "Введите количество целым числом от 1 до 100.",
            "price_manual": "Введите цену в евро, например 29,95.",
        }
        await message.answer(prompts[step], reply_markup=markup(token, [], extra=back))
    elif step == "quantity":
        await message.answer(
            f"Цвет: {data['color']} · Размер: {data['size']}\nСколько штук?",
            reply_markup=markup(
                token,
                [("1", "qty_1"), ("2", "qty_2"), ("3", "qty_3")],
                columns=3,
                extra=[("Другое количество", "manual"), *back],
            ),
        )
    elif step in ("price", "reprice"):
        price = data["option_price"] if step == "reprice" else data["suggested_price"]
        text = f"Цена: {price} EUR. Подтверждаете?"
        if step == "reprice":
            text = (
                f"Для цвета «{data['color']}» и размера {data['size']} "
                f"цена на сайте: {price} EUR. Подтверждаете?"
            )
        await message.answer(
            text,
            reply_markup=markup(
                token,
                [("Да", "yes"), ("Изменить цену", "edit")],
                extra=back if step == "reprice" else (),
            ),
        )


async def begin_options(message, conversation):
    data = conversation.data
    if len(data.get("variants", [])) == 1:
        conversation.data = set_color(data, 0)
        await show_step(message, conversation, "size")
    else:
        await show_step(message, conversation, "color")


async def size_selected(message, conversation, size, price=None):
    data = conversation.data
    variant = selected_variant(data)
    candidate = price or (variant or {}).get("price_eur")
    conversation.data = {**data, "size": size, "option_price": candidate}
    if variant and not candidate and data.get("price_source") != "manual":
        conversation.data = {**conversation.data, "price_return": "quantity", "price_back": "size"}
        await message.answer("Для выбранного варианта цена не получена. Укажите ее вручную.")
        await show_step(message, conversation, "price_manual")
    elif (
        candidate
        and data.get("price_source") != "manual"
        and Decimal(candidate) != Decimal(data["suggested_price"])
    ):
        await show_step(message, conversation, "reprice")
    else:
        await show_step(message, conversation, "quantity")


def item_command(data, quantity):
    return ItemInput(
        url=data.get("selected_url", data["url"]),
        name=data.get("name"),
        price=data["suggested_price"],
        color=data["color"],
        size=data["size"],
        quantity=quantity,
    )


async def accept_text(message, conversation, raw):
    data = conversation.data
    step = data.get("item_step")
    if step in ("color", "color_manual"):
        if not 1 <= len(raw) <= 128:
            raise OrderError("Введите цвет длиной до 128 символов")
        # A typed known color must retain its sizes and variant URL too.
        index = next(
            (
                i
                for i, c in enumerate(data.get("variants", []))
                if c["name"].casefold() == raw.casefold()
            ),
            None,
        )
        if index is not None:
            conversation.data = set_color(data, index)
        else:
            conversation.data = {
                **data,
                "color": raw,
                "selected_variant": None,
                "selected_url": data["url"],
                "size": None,
            }
        await show_step(message, conversation, "size")
    elif step in ("size", "size_manual"):
        if not 1 <= len(raw) <= 64:
            raise OrderError("Введите размер длиной до 64 символов")
        variant = selected_variant(data)
        size = next(
            (
                s
                for s in (variant or {}).get("sizes", [])
                if s["name"].casefold() == raw.casefold()
            ),
            None,
        )
        await size_selected(
            message,
            conversation,
            size["name"] if size else raw,
            size.get("price_eur") if size else None,
        )
    elif step in ("quantity", "quantity_manual"):
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 100:
            raise OrderError("Введите количество целым числом от 1 до 100")
        return item_command(data, int(raw))
    elif step == "price_manual":
        try:
            price = ItemInput(
                url=data["url"],
                price=raw.replace(",", "."),
                size="-",
                color="-",
                quantity=1,
            ).price
        except ValidationError:
            raise OrderError("Введите только цену в евро, например 29,95")
        conversation.data = {
            **data,
            "suggested_price": str(price),
            "price_source": "manual",
        }
        if data.get("price_return") == "quantity":
            await show_step(message, conversation, "quantity")
        else:
            await begin_options(message, conversation)
    else:
        raise OrderError("Используйте кнопки под последним сообщением бота")
    return None


async def accept_action(message, conversation, action):
    data = conversation.data
    step = data.get("item_step")
    if action == "back":
        previous = {
            "color": "price",
            "color_manual": "color",
            "size": "color",
            "size_manual": "size",
            "quantity": "size",
            "quantity_manual": "quantity",
            "reprice": "size",
            "price_manual": data.get("price_back", "price"),
        }.get(step)
        if not previous:
            raise OrderError("Используйте кнопки под последним сообщением")
        await show_step(message, conversation, previous)
    elif action == "manual" and step in ("color", "size", "quantity"):
        await show_step(message, conversation, f"{step}_manual")
    elif step == "color" and action == "skip":
        conversation.data = {
            **data,
            "color": "-",
            "selected_variant": None,
            "selected_url": data["url"],
            "size": None,
        }
        await show_step(message, conversation, "size")
    elif step == "color" and action.startswith("color_"):
        index = int(action.removeprefix("color_"))
        if not 0 <= index < len(data.get("variants", [])):
            raise OrderError("Выберите цвет из списка")
        conversation.data = set_color(data, index)
        await show_step(message, conversation, "size")
    elif step == "size" and action.startswith("size_"):
        index = int(action.removeprefix("size_"))
        sizes = (selected_variant(data) or {}).get("sizes", [])
        if not 0 <= index < len(sizes):
            raise OrderError("Выберите размер из списка")
        size = sizes[index]
        await size_selected(message, conversation, size["name"], size.get("price_eur"))
    elif step == "quantity" and action in ("qty_1", "qty_2", "qty_3"):
        return item_command(data, int(action[-1]))
    elif step in ("price", "reprice") and action == "yes":
        if step == "reprice":
            conversation.data = {**data, "suggested_price": data["option_price"]}
            await show_step(message, conversation, "quantity")
        else:
            await begin_options(message, conversation)
    elif step in ("price", "reprice") and action == "edit":
        conversation.data = {
            **data,
            "price_return": "quantity" if step == "reprice" else "color",
            "price_back": step,
        }
        await show_step(message, conversation, "price_manual")
    else:
        raise OrderError("Используйте кнопки под последним сообщением")
    return None
