import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, Customer, RecipientInvite, UserRole
from app.services.orders import OrderError


async def create_invite(session: AsyncSession, customer: Customer) -> str:
    token = secrets.token_urlsafe(24)
    session.add(
        RecipientInvite(
            customer_id=customer.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    return "https://t.me/spain_oders_bot?start=recv_" + token


async def redeem_invite(
    session: AsyncSession,
    token: str,
    telegram_user_id: int,
    first_name: str,
    last_name: str | None,
    username: str | None,
):
    invite = await session.scalar(
        select(RecipientInvite)
        .where(RecipientInvite.token_hash == hashlib.sha256(token.encode()).hexdigest())
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if invite is None or invite.used_at or invite.expires_at < now:
        raise OrderError("Приглашение недействительно или уже использовано")
    customer = await session.scalar(
        select(Customer).where(Customer.id == invite.customer_id).with_for_update()
    )
    user = await session.scalar(select(AppUser).where(AppUser.telegram_user_id == telegram_user_id))
    if customer.app_user_id is not None:
        raise OrderError("Получатель уже подключен к уведомлениям")
    if user and await session.scalar(select(Customer.id).where(Customer.app_user_id == user.id)):
        raise OrderError("Этот Telegram-аккаунт уже привязан к другому получателю")
    if user is None:
        user = AppUser(
            telegram_user_id=telegram_user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            role=UserRole.CUSTOMER,
        )
        session.add(user)
        await session.flush()
    customer.app_user_id = user.id
    invite.used_at = now
    return customer
