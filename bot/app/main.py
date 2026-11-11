import asyncio
import re
from io import BytesIO
from uuid import UUID

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.services.drafts import DraftError, DraftService, OpenDraftCommand
from app.services.payment_evidence import PaymentEvidenceError, PaymentEvidenceService
from app.services.users import UserService
from bot_app.notifications import notification_worker

router = Router()
dispatcher = Dispatcher()
dispatcher.include_router(router)
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
SIZES = ("XS", "S", "M", "L", "XL")


def size_keyboard(draft_id: UUID) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=size, callback_data=f"draft:size:{draft_id}:{size}")
               for size in SIZES]
    buttons.append(InlineKeyboardButton(text="Без размера", callback_data=f"draft:size:{draft_id}:-"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:3], buttons[3:]])


def confirm_keyboard(draft_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Добавить заказ", callback_data=f"draft:confirm:{draft_id}")]])


def skip_comment_keyboard(draft_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустить комментарий", callback_data=f"draft:comment:skip:{draft_id}")
    ]])


def skip_payment_keyboard(item_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Не оплачивал / пропустить", callback_data=f"payment:skip:{item_id}")
    ]])


def webapp_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍 Открыть мои заказы", web_app=WebAppInfo(url=url))]])


def profile_keyboard(url: str) -> InlineKeyboardMarkup:
    separator = "&" if "?" in url else "?"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📝 Заполнить профиль",
            web_app=WebAppInfo(url=f"{url}{separator}view=profile"),
        )]])


def persistent_webapp_keyboard(url: str) -> ReplyKeyboardMarkup:
    separator = "&" if "?" in url else "?"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="📝 Заполнить форму",
                web_app=WebAppInfo(url=f"{url}{separator}view=profile"),
            )],
            [KeyboardButton(text="🛍 Мои заказы", web_app=WebAppInfo(url=url))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def identity(event: Message | CallbackQuery):
    user = event.from_user
    if user is None:
        raise RuntimeError("Telegram user is unavailable")
    async with SessionFactory() as session, session.begin():
        app_user, customer = await UserService(session).register_customer(
            user.id, user.first_name, user.last_name, user.username)
        return app_user.id, customer.id, app_user.role


@router.message(CommandStart())
async def start(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    _, customer_id, role = await identity(message)
    webapp_url = get_settings().telegram_webapp_url
    await message.answer(
        "Добро пожаловать. Чтобы сделать заказ, отправьте мне ссылку на товар.",
        reply_markup=persistent_webapp_keyboard(webapp_url) if webapp_url else None,
    )
    if role.value == "CUSTOMER":
        async with SessionFactory() as session:
            profile_complete = await UserService(session).has_complete_delivery_profile(customer_id)
        if not profile_complete and webapp_url:
            await message.answer(
                "Перед первым заказом заполните контактные данные и адрес. "
                "Нажмите кнопку ниже. Если она не открывается, используйте кнопку "
                "«Мои заказы» в меню бота — приложение само откроет раздел «Профиль».",
                reply_markup=profile_keyboard(webapp_url),
            )


@router.message(Command("profile"))
async def open_profile(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    _, _, role = await identity(message)
    if role.value != "CUSTOMER":
        await message.answer("Для этого аккаунта включён режим просмотра.")
        return
    webapp_url = get_settings().telegram_webapp_url
    if not webapp_url:
        await message.answer("Анкета временно недоступна. Попробуйте позже.")
        return
    await message.answer(
        "Откройте анкету и заполните контактные данные и адрес:",
        reply_markup=profile_keyboard(webapp_url),
    )


@router.message(F.text, F.reply_to_message.is_(None))
async def receive_url(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    match = URL_RE.search(message.text or "")
    if match is None:
        await message.answer("Пришлите ссылку на товар, начинающуюся с https://")
        return
    app_user_id, customer_id, role = await identity(message)
    if role.value == "VIEWER":
        await message.answer("Для этого аккаунта включён режим просмотра без создания заказов.")
        return
    async with SessionFactory() as session:
        profile_complete = await UserService(session).has_complete_delivery_profile(customer_id)
    if not profile_complete:
        webapp_url = get_settings().telegram_webapp_url
        await message.answer(
            "Перед первым заказом заполните ФИО, телефон и адрес в разделе «Профиль», "
            "затем отправьте ссылку ещё раз.",
            reply_markup=persistent_webapp_keyboard(webapp_url) if webapp_url else None,
        )
        return
    async with SessionFactory() as session, session.begin():
        draft = await DraftService(session).open(OpenDraftCommand(
            app_user_id, message.chat.id, message.message_id, match.group(0)))
        draft_id = draft.id
    await message.answer("Какой размер вам нужен?", reply_markup=size_keyboard(draft_id))


@router.callback_query(F.data.startswith("draft:size:"))
async def choose_size(callback: CallbackQuery):
    if callback.message is None or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer()
        return
    _, _, raw_id, raw_size = (callback.data or "").split(":", 3)
    app_user_id, _, _ = await identity(callback)
    async with SessionFactory() as session, session.begin():
        await DraftService(session).set_size(
            UUID(raw_id), app_user_id, None if raw_size == "-" else raw_size)
    await callback.message.edit_text(
        f"Комментарий к черновику {raw_id}\n"
        f"Размер: {raw_size if raw_size != '-' else 'без размера'}.\n\n"
        "Ответьте на это сообщение комментарием к заказу или нажмите «Пропустить».",
        reply_markup=skip_comment_keyboard(UUID(raw_id)))
    await callback.answer()


@router.message(F.reply_to_message.text.startswith("Комментарий к черновику "))
async def receive_comment(message: Message):
    if message.chat.type != ChatType.PRIVATE or not message.text:
        return
    match = re.search(r"Комментарий к черновику ([0-9a-f-]{36})", message.reply_to_message.text or "")
    if match is None:
        return
    app_user_id, _, _ = await identity(message)
    draft_id = UUID(match.group(1))
    async with SessionFactory() as session, session.begin():
        await DraftService(session).set_comment(draft_id, app_user_id, message.text)
    await message.answer("Комментарий сохранён. Добавить заказ?", reply_markup=confirm_keyboard(draft_id))


@router.callback_query(F.data.startswith("draft:comment:skip:"))
async def skip_comment(callback: CallbackQuery):
    if callback.message is None or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer()
        return
    draft_id = UUID((callback.data or "").rsplit(":", 1)[-1])
    app_user_id, _, _ = await identity(callback)
    async with SessionFactory() as session, session.begin():
        await DraftService(session).set_comment(draft_id, app_user_id, None)
    await callback.message.edit_text(
        "Комментарий пропущен. Добавить заказ?", reply_markup=confirm_keyboard(draft_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("draft:confirm:"))
async def confirm(callback: CallbackQuery):
    if callback.message is None or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer()
        return
    raw_id = (callback.data or "").rsplit(":", 1)[-1]
    app_user_id, customer_id, _ = await identity(callback)
    try:
        async with SessionFactory() as session, session.begin():
            item = await DraftService(session).confirm(UUID(raw_id), app_user_id, customer_id)
            item_id = item.id
    except DraftError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.message.edit_text(
        f"✅ Заказ {item_id} успешно оформлен. Статус: ожидает покупки.\n"
        "Мы уведомим вас здесь, когда статус изменится.\n\n"
        f"Оплата по заказу {item_id}\n"
        "Если вы уже оплатили товар, ответьте на это сообщение фотографией или скриншотом "
        "чека. Можно также прислать текст с информацией об оплате.",
        reply_markup=skip_payment_keyboard(item_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("payment:skip:"))
async def skip_payment(callback: CallbackQuery):
    if callback.message is not None:
        item_id = (callback.data or "").rsplit(":", 1)[-1]
        await callback.message.edit_reply_markup(reply_markup=None)
        url = get_settings().telegram_webapp_url
        await callback.message.answer(
            f"✅ Заказ {item_id} оформлен. Информация об оплате пропущена. "
            "На этом оформление завершено; мы сообщим здесь об изменениях статуса.",
            reply_markup=persistent_webapp_keyboard(url) if url else None,
        )
    await callback.answer()


@router.message(F.reply_to_message.text.contains("Оплата по заказу "))
async def receive_payment_evidence(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    match = re.search(r"Оплата по заказу ([0-9a-f-]{36})", message.reply_to_message.text or "")
    if match is None:
        return
    if message.text and message.text.strip().lower() in {"нет", "не оплачивал", "пропустить"}:
        url = get_settings().telegram_webapp_url
        await message.answer(
            f"✅ Заказ {match.group(1)} оформлен. Информация об оплате пропущена. "
            "На этом оформление завершено; мы сообщим здесь об изменениях статуса.",
            reply_markup=persistent_webapp_keyboard(url) if url else None,
        )
        return
    app_user_id, _, _ = await identity(message)
    content = None
    mime_type = None
    original_filename = None
    telegram_file_id = None
    telegram_file_unique_id = None
    if message.photo:
        photo = message.photo[-1]
        buffer = BytesIO()
        await message.bot.download(photo, destination=buffer)
        content = buffer.getvalue()
        mime_type = "image/jpeg"
        original_filename = f"telegram-{photo.file_unique_id}.jpg"
        telegram_file_id = photo.file_id
        telegram_file_unique_id = photo.file_unique_id
    elif message.document and message.document.mime_type in {"image/jpeg", "image/png", "image/webp"}:
        buffer = BytesIO()
        await message.bot.download(message.document, destination=buffer)
        content = buffer.getvalue()
        mime_type = message.document.mime_type
        original_filename = message.document.file_name
        telegram_file_id = message.document.file_id
        telegram_file_unique_id = message.document.file_unique_id
    note = message.caption or message.text
    try:
        async with SessionFactory() as session, session.begin():
            await PaymentEvidenceService(session, get_settings().payment_proof_dir).create(
                UUID(match.group(1)),
                app_user_id,
                admin=False,
                note=note,
                content=content,
                mime_type=mime_type,
                original_filename=original_filename,
                telegram_file_id=telegram_file_id,
                telegram_file_unique_id=telegram_file_unique_id,
            )
    except PaymentEvidenceError as exc:
        await message.answer(f"Не удалось сохранить подтверждение: {exc}")
        return
    url = get_settings().telegram_webapp_url
    await message.answer(
        f"✅ Информация об оплате сохранена. Заказ {match.group(1)} оформлен. "
        "На этом оформление завершено; мы сообщим здесь об изменениях статуса.",
        reply_markup=persistent_webapp_keyboard(url) if url else None,
    )


async def main():
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required to run the bot profile")
    async with Bot(token=token) as bot:
        if settings.telegram_webapp_url:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="Мои заказы",
                web_app=WebAppInfo(url=settings.telegram_webapp_url),
            ))
        worker = asyncio.create_task(notification_worker(bot))
        try:
            await dispatcher.start_polling(bot)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
