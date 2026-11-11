"""Persistent, individually validated recipient steps."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pydantic import ValidationError

from app.models import Customer, CustomerAddress
from app.schemas.orders import RecipientInput, validate_recipient_step
from app.services.orders import OrderService

STEPS = (
    (
        "recipient_name",
        "Укажите имя и фамилию получателя только английскими буквами A–Z, как в паспорте.",
    ),
    ("phone", "Укажите контактный телефон получателя с кодом страны."),
    (
        "telegram_username",
        "Укажите Telegram username получателя или нажмите «Пропустить». Это поле необязательное.",
    ),
    ("postal_code", "Укажите индекс в России — 6 цифр."),
    ("region", "Укажите регион английскими буквами: например, Moscow Oblast."),
    ("city", "Укажите город английскими буквами: например, Moscow."),
    (
        "address_line1",
        "Укажите улицу, дом и квартиру английскими буквами: например, Tverskaya St., 10, Apt. 5.",
    ),
)


def begin_recipient_form(conversation):
    conversation.state = "RECIPIENT"
    conversation.data = {"recipient_step": 0, "recipient_values": {}}
    conversation.active_order_id = None


async def show_recipient_step(message, conversation):
    step = conversation.data.get("recipient_step", 0)
    field, prompt = STEPS[step]
    rows = []
    if field == "telegram_username":
        rows.append(
            [
                InlineKeyboardButton(
                    text="Пропустить", callback_data=f"recipient_form:skip:{step}"
                )
            ]
        )
    if step:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Назад", callback_data=f"recipient_form:back:{step}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Отменить ввод", callback_data=f"recipient_form:cancel:{step}"
            )
        ]
    )
    await message.answer(
        f"Получатель · шаг {step + 1} из {len(STEPS)}\n{prompt}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def accept_recipient_value(message, session, actor, conversation, raw):
    step = conversation.data.get("recipient_step", 0)
    field = STEPS[step][0]
    if (
        field == "telegram_username"
        and isinstance(raw, str)
        and raw.casefold() in ("-", "нет", "пропустить")
    ):
        raw = None
    try:
        value = validate_recipient_step(field, raw)
    except (ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            detail = "Проверьте длину введенного значения."
        else:
            detail = str(exc)
        await message.answer(detail)
        await show_recipient_step(message, conversation)
        return None
    values = {**conversation.data.get("recipient_values", {}), field: value}
    if step < len(STEPS) - 1:
        conversation.data = {"recipient_step": step + 1, "recipient_values": values}
        await show_recipient_step(message, conversation)
        return None
    try:
        command = RecipientInput(**values)
    except ValidationError as exc:
        # A form started before a validation update may contain an old address.
        invalid = exc.errors()[0]
        field = invalid["loc"][0]
        step = next(i for i, (name, _) in enumerate(STEPS) if name == field)
        conversation.data = {"recipient_step": step, "recipient_values": values}
        await message.answer(str(invalid["msg"]).removeprefix("Value error, "))
        await show_recipient_step(message, conversation)
        return None
    customer = Customer(
        stylist_id=actor.id,
        display_name=command.recipient_name,
        phone=command.phone,
        telegram_username=command.telegram_username,
    )
    session.add(customer)
    await session.flush()
    address = CustomerAddress(
        customer_id=customer.id,
        label="Основной адрес",
        country_code="RU",
        is_default=True,
        **command.model_dump(exclude={"telegram_username"}),
    )
    session.add(address)
    await session.flush()
    order = await OrderService(session).create(customer.id, address.id, actor.id)
    conversation.active_order_id = order.id
    conversation.state, conversation.data = "IDLE", {}
    return order
