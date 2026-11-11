"""Private stylist bot. Conversation state and orders survive restarts."""

import asyncio
import contextlib
import hashlib
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import (
    BotConversation,
    Customer,
    CustomerAddress,
    IdempotencyKey,
    OrderQuote,
    StylistOrder,
)
from app.schemas.orders import ItemInput
from app.services.operators import operator_role, register_operator
from app.services.orders import OrderError, OrderService
from app.services.product_import import identify_product, import_product
from app.services.rates import current_rate

from .notifications import notification_worker
from .recipient_form import (
    accept_recipient_value,
    begin_recipient_form,
    show_recipient_step,
)

router = Router()
dispatcher = Dispatcher()
dispatcher.include_router(router)


def keyboard():
    rows = [
        [KeyboardButton(text="Новый заказ"), KeyboardButton(text="Мои заказы")],
        [KeyboardButton(text="Продолжить позже"), KeyboardButton(text="Расчет")],
        [KeyboardButton(text="Завершить заказ")],
    ]
    if get_settings().telegram_webapp_url:
        rows.append(
            [
                KeyboardButton(
                    text="Открыть приложение",
                    web_app=WebAppInfo(url=get_settings().telegram_webapp_url),
                )
            ]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def buttons(values):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=value)]
            for label, value in values
        ]
    )


class OperatorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        chat = (
            event.message.chat
            if isinstance(event, CallbackQuery) and event.message
            else getattr(event, "chat", None)
        )
        if not user or not chat or chat.type != ChatType.PRIVATE:
            return
        try:
            operator_role(user.id)
        except PermissionError:
            if isinstance(event, Message):
                from app.models import AppUser
                from app.services.recipient_invites import redeem_invite

                try:
                    async with SessionFactory() as session, session.begin():
                        await session.execute(
                            text("SELECT pg_advisory_xact_lock(:key)"), {"key": user.id}
                        )
                        if (event.text or "").startswith("/start recv_"):
                            token = event.text.split("recv_", 1)[1].strip()
                            await redeem_invite(
                                session,
                                token,
                                user.id,
                                user.first_name,
                                user.last_name,
                                user.username,
                            )
                            await event.answer(
                                "Уведомления подключены. Вы будете получать статусы и трек-номера ваших заказов."
                            )
                            return
                        registered = await session.scalar(
                            select(Customer.id)
                            .join(AppUser, Customer.app_user_id == AppUser.id)
                            .where(AppUser.telegram_user_id == user.id)
                        )
                        if registered:
                            await event.answer(
                                "Вы подключены к уведомлениям о заказах. Оформлением занимается ваш стилист."
                            )
                            return
                except OrderError as exc:
                    await event.answer(str(exc))
                    return
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            else:
                await event.answer("Доступ к оформлению заказов не разрешен.")
            return
        try:
            async with SessionFactory() as session, session.begin():
                # Serialize one user's actions even across polling workers/retries.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": user.id}
                )
                actor = await register_operator(
                    session, user.id, user.first_name, user.last_name, user.username
                )
                conversation = await session.get(BotConversation, user.id)
                if conversation is None:
                    conversation = BotConversation(
                        telegram_user_id=user.id, state="IDLE", data={}
                    )
                    session.add(conversation)
                    await session.flush()
                event_key = (
                    f"callback:{event.id}"
                    if isinstance(event, CallbackQuery)
                    else f"message:{chat.id}:{event.message_id}"
                )
                scope = "stylist_bot"
                existing = await session.scalar(
                    select(IdempotencyKey.id).where(
                        IdempotencyKey.scope == scope, IdempotencyKey.key == event_key
                    )
                )
                if existing:
                    if isinstance(event, CallbackQuery):
                        await event.answer("Уже обработано")
                    return
                data.update(session=session, actor=actor, conversation=conversation)
                await handler(event, data)
                session.add(
                    IdempotencyKey(
                        scope=scope,
                        key=event_key,
                        request_hash=hashlib.sha256(event_key.encode()).hexdigest(),
                        expires_at=datetime(2100, 1, 1, tzinfo=timezone.utc),
                    )
                )
        except (OrderError, ValueError, PermissionError) as exc:
            target = event.message if isinstance(event, CallbackQuery) else event
            if target:
                detail = (
                    "Проверьте введенные данные."
                    if isinstance(exc, ValidationError)
                    else str(exc)
                )
                await target.answer(detail[:3500], reply_markup=keyboard())
            if isinstance(event, CallbackQuery):
                await event.answer()
        except Exception:
            # Do not include database connection details or tokens in chat.
            import logging

            logging.getLogger(__name__).exception("Bot action failed")
            target = event.message if isinstance(event, CallbackQuery) else event
            if target:
                await target.answer(
                    "Не удалось выполнить действие. Данные заказа сохранены; попробуйте еще раз.",
                    reply_markup=keyboard(),
                )
            if isinstance(event, CallbackQuery):
                await event.answer()


router.message.outer_middleware(OperatorMiddleware())
router.callback_query.outer_middleware(OperatorMiddleware())


@router.message(CommandStart())
async def start(message: Message, conversation, **kwargs):
    if conversation.state == "RECIPIENT":
        await show_recipient_step(message, conversation)
        return
    await message.answer(
        "Заказы из Испании. Создайте заказ или выберите сохраненный в разделе «Мои заказы».",
        reply_markup=keyboard(),
    )


@router.message(F.text == "Новый заказ")
@router.message(Command("new"))
async def new_order(message: Message, session, actor, conversation):
    query = (
        select(Customer, CustomerAddress)
        .join(CustomerAddress, CustomerAddress.customer_id == Customer.id)
        .where(Customer.stylist_id == actor.id)
    )
    rows = (await session.execute(query.order_by(Customer.display_name))).all()
    choices = [(f"{c.display_name} · {a.city}", f"recipient:{a.id}") for c, a in rows]
    choices.append(("Новый получатель", "new_recipient"))
    await message.answer(
        "Выберите сохраненного получателя или добавьте нового:",
        reply_markup=buttons(choices[:80]),
    )


@router.callback_query(F.data == "new_recipient")
async def new_recipient(callback: CallbackQuery, conversation, **kwargs):
    begin_recipient_form(conversation)
    await show_recipient_step(callback.message, conversation)
    await callback.answer()


@router.callback_query(F.data.startswith("recipient_form:"))
async def recipient_navigation(callback: CallbackQuery, session, actor, conversation):
    if conversation.state != "RECIPIENT":
        await callback.answer("Эта форма уже закрыта")
        return
    _, action, step_text = callback.data.split(":")
    step = conversation.data.get("recipient_step", 0)
    if int(step_text) != step:
        await callback.answer("Используйте кнопки текущего шага")
        await show_recipient_step(callback.message, conversation)
        return
    if action == "cancel":
        conversation.state, conversation.data = "IDLE", {}
        await callback.message.answer(
            "Ввод получателя отменен. Сохраненные заказы остались в «Мои заказы».",
            reply_markup=keyboard(),
        )
    elif action == "back" and step:
        conversation.data = {**conversation.data, "recipient_step": step - 1}
        await show_recipient_step(callback.message, conversation)
    elif action == "skip" and step == 2:
        await accept_recipient_value(
            callback.message, session, actor, conversation, None
        )
    await callback.answer()


@router.callback_query(F.data.startswith("recipient:"))
async def choose_recipient(callback: CallbackQuery, session, actor, conversation):
    address = await session.get(CustomerAddress, UUID(callback.data.split(":")[1]))
    if address is None:
        raise OrderError("Адрес не найден")
    order = await OrderService(session).create(
        address.customer_id, address.id, actor.id
    )
    conversation.active_order_id = order.id
    conversation.state, conversation.data = "IDLE", {}
    await callback.message.answer(
        f"Заказ {order.number} создан. Пришлите ссылку на товар Zara или H&M.",
        reply_markup=keyboard(),
    )
    await callback.answer()


@router.message(F.text == "Мои заказы")
@router.message(Command("orders"))
async def list_orders(message: Message, session, actor, **kwargs):
    orders = (
        await session.scalars(
            select(StylistOrder)
            .where(StylistOrder.stylist_id == actor.id)
            .order_by(StylistOrder.created_at.desc())
            .limit(80)
        )
    ).all()
    if not orders:
        await message.answer("Сохраненных заказов пока нет.", reply_markup=keyboard())
        return
    await message.answer(
        "Выберите заказ:",
        reply_markup=buttons(
            [
                (
                    f"{o.number} · {o.address_snapshot['recipient_name']} · {o.state}",
                    f"order:{o.id}",
                )
                for o in orders
            ]
        ),
    )


@router.callback_query(F.data.startswith("order:"))
async def select_order(callback: CallbackQuery, session, actor, conversation):
    order = await OrderService(session).get(UUID(callback.data.split(":")[1]), actor.id)
    conversation.active_order_id = order.id
    conversation.state, conversation.data = "IDLE", {}
    await callback.message.answer(
        f"Выбран {order.number}. Получатель: {order.address_snapshot['recipient_name']}.\nСостояние: {order.state}.",
        reply_markup=keyboard(),
    )
    if order.active_quote_id:
        await send_quote(
            callback.message,
            session,
            order,
            await session.get(OrderQuote, order.active_quote_id),
        )
    elif (order.intake_snapshot or {}).get("urls"):
        await prompt_pending(callback.message, order, conversation)
    await callback.answer()


@router.message(F.text == "Продолжить позже")
async def pause(message: Message, conversation, **kwargs):
    if conversation.state == "RECIPIENT":
        await message.answer(
            "Сначала закончите ввод текущего товара или получателя. Уже оформленные товары сохранены."
        )
        return
    conversation.active_order_id = None
    conversation.state, conversation.data = "IDLE", {}
    await message.answer(
        "Заказ сохранен. Вернуться к нему можно через «Мои заказы». Можно создать другой заказ.",
        reply_markup=keyboard(),
    )


async def send_quote(message, session, order, quote):
    from app.api.orders import order_details

    details = await order_details(session, order)
    if quote is None:
        await message.answer(
            f"Заказ {order.number}: формирование завершено, все товары оплачены.",
            reply_markup=keyboard(),
        )
        return
    await message.answer(
        f"Заказ {order.number}\nОбщая стоимость активных товаров с комиссией: {details['total_eur']} EUR\nРанее оплачено: {details['paid_rub']} RUB\n\nК оплате за новые позиции: {quote.total_eur} EUR\nКурс ЦБ на {quote.rate_date:%d.%m.%Y}: {quote.eur_rub_rate}\nК оплате в рублях (+5%): {quote.due_rub} RUB\n\nНажмите кнопку ниже, затем пришлите скриншот оплаты. Сумма расчета сохранится, даже если оплатите позже.",
        reply_markup=buttons(
            [("Прикрепить скриншот к этому расчету", f"pay:{quote.id}")]
        ),
    )


@router.message(F.text.in_({"Расчет", "Завершить заказ"}))
async def calculate(message: Message, session, actor, conversation):
    if not conversation.active_order_id:
        raise OrderError("Сначала выберите заказ в разделе «Мои заказы»")
    if conversation.state != "IDLE":
        raise OrderError("Сначала закончите ввод текущего товара")
    service = OrderService(session)
    order = await service.get(conversation.active_order_id, actor.id)
    close = message.text == "Завершить заказ"
    if order.state == "AWAITING_PAYMENT":
        quote = await session.get(OrderQuote, order.active_quote_id)
        if quote.close_order != close:
            raise OrderError("Сначала прикрепите скриншот к текущему расчету")
    else:
        rate = await current_rate(session)
        quote = await service.issue_quote(order.id, actor.id, rate, close)
    await send_quote(message, session, order, quote)


@router.callback_query(F.data.startswith("pay:"))
async def choose_payment(callback: CallbackQuery, session, actor, conversation):
    quote = await session.get(OrderQuote, UUID(callback.data.split(":")[1]))
    if quote is None:
        raise OrderError("Расчет не найден")
    order = await OrderService(session).get(quote.order_id, actor.id)
    if order.active_quote_id != quote.id or quote.state != "ISSUED":
        raise OrderError("Этот расчет уже не ожидает оплаты")
    conversation.active_order_id = order.id
    conversation.state = "PAYMENT"
    conversation.data = {"quote_id": str(quote.id)}
    await callback.message.answer(
        f"Пришлите скриншот для заказа {order.number}, сумма {quote.due_rub} RUB."
    )
    await callback.answer()


@router.message(F.photo | F.document)
async def screenshot(message: Message, session, actor, conversation, bot: Bot):
    if conversation.state != "PAYMENT" or not conversation.active_order_id:
        raise OrderError("Сначала нажмите «Прикрепить скриншот» под нужным расчетом")
    file = message.photo[-1] if message.photo else message.document
    mime = "image/jpeg" if message.photo else (message.document.mime_type or "")
    if mime not in ("image/jpeg", "image/png") or (file.file_size or 0) > 10_000_000:
        raise OrderError("Пришлите изображение JPEG или PNG не более 10 МБ")
    stream = BytesIO()
    await bot.download(file, destination=stream)
    content = stream.getvalue()
    if len(content) > 10_000_000 or not (
        content.startswith(b"\xff\xd8\xff") or content.startswith(b"\x89PNG\r\n\x1a\n")
    ):
        raise OrderError("Файл не является поддерживаемым изображением")
    filename = uuid4().hex + (".jpg" if mime == "image/jpeg" else ".png")
    folder = Path(get_settings().payment_proof_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(content)
    await OrderService(session).confirm_payment(
        conversation.active_order_id,
        UUID(conversation.data["quote_id"]),
        actor.id,
        file_id=file.file_id,
        stored_filename=filename,
        mime_type=mime,
        chat_id=message.chat.id,
        message_id=message.message_id,
        paid_at=message.date,
    )
    conversation.state, conversation.data, conversation.active_order_id = (
        "IDLE",
        {},
        None,
    )
    await message.answer(
        "Скриншот сохранен, оплата учтена. Можно создать другой заказ или выбрать сохраненный.",
        reply_markup=keyboard(),
    )


@router.message(F.text)
async def receive_text(message: Message, session, actor, conversation):
    raw = message.text.strip()
    if conversation.state == "RECIPIENT":
        order = await accept_recipient_value(message, session, actor, conversation, raw)
        if order:
            await message.answer(
                f"Получатель сохранен. Заказ {order.number} создан. Пришлите ссылку на товар.",
                reply_markup=keyboard(),
            )
        return
    links = raw.split()
    if links and all(link.startswith("https://") for link in links):
        if not conversation.active_order_id or conversation.state == "PAYMENT":
            raise OrderError("Сначала выберите заказ для добавления товаров")
        order = await OrderService(session).get(conversation.active_order_id, actor.id)
        if order.state != "DRAFT":
            raise OrderError("Добавление товаров доступно только в черновик")
        for link in links:
            identify_product(link)
        old = (order.intake_snapshot or {}).get("urls", [])
        if len(old) + len(links) > 100:
            raise OrderError(
                "Заполните параметры ранее присланных товаров (лимит очереди 100 ссылок)"
            )
        order.intake_snapshot = {**(order.intake_snapshot or {}), "urls": old + links}
        if conversation.state == "ITEM":
            await message.answer(
                f"Ссылки сохранены. В очереди: {len(old) + len(links)}. Сначала заполните параметры текущего товара."
            )
        else:
            await prompt_pending(message, order, conversation)
        return
    if conversation.state == "ITEM":
        fields = [value.strip() for value in raw.split(";")]
        if len(fields) != 4:
            raise OrderError(
                "Формат: цена в евро; размер; цвет; количество. Например: 29,99; M; черный; 1"
            )
        values = conversation.data
        command = ItemInput(
            url=values["url"],
            price=fields[0].replace(",", "."),
            size=fields[1],
            color=fields[2],
            quantity=fields[3],
            name=values.get("name"),
        )
        await OrderService(session).add_item(
            conversation.active_order_id, actor.id, **command.model_dump()
        )
        order = await OrderService(session).get(conversation.active_order_id, actor.id)
        remaining = (order.intake_snapshot or {}).get("urls", [])[1:]
        order.intake_snapshot = {"urls": remaining}
        conversation.state, conversation.data = "IDLE", {}
        await message.answer(
            "Товар сохранен. Пришлите следующую ссылку или выберите действие внизу.",
            reply_markup=keyboard(),
        )
        if remaining:
            await prompt_pending(message, order, conversation)
        return
    if not conversation.active_order_id:
        raise OrderError(
            "Создайте новый заказ или выберите сохраненный через «Мои заказы»"
        )
    if conversation.state == "PAYMENT":
        raise OrderError("Ожидается изображение со скриншотом оплаты")
    order = await OrderService(session).get(conversation.active_order_id, actor.id)
    if order.state != "DRAFT":
        raise OrderError(
            "Добавление товаров сейчас недоступно. Проверьте состояние заказа в приложении"
        )
    raise OrderError(
        "Пришлите одну или несколько ссылок на товары Zara/H&M либо выберите действие внизу"
    )


async def prompt_pending(message, order, conversation):
    url = order.intake_snapshot["urls"][0]
    imported = await import_product(url)
    conversation.state = "ITEM"
    conversation.data = {"url": url, "name": imported.name}
    summary = imported.name or imported.product.merchant
    price = (
        f"Найденная цена: {imported.price_eur} EUR."
        if imported.price_eur is not None
        else "Автоматически получить цену не удалось."
    )
    await message.answer(
        f"{summary}\n{url}\n{price}\nВведите или подтвердите цену, размер, цвет и количество через точку с запятой:\n29,99; M; черный; 1",
        reply_markup=keyboard(),
    )


async def exchange_rate_worker():
    while True:
        try:
            async with SessionFactory() as session, session.begin():
                await current_rate(session)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Daily CBR rate refresh unavailable; will retry"
            )
        await asyncio.sleep(300)


async def main():
    bot = Bot(get_settings().telegram_bot_token)
    worker = asyncio.create_task(notification_worker(bot))
    rates = asyncio.create_task(exchange_rate_worker())
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        rates.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        with contextlib.suppress(asyncio.CancelledError):
            await rates
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
