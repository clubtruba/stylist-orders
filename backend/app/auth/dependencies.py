from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.telegram import TelegramAuthError, validate_init_data
from app.core.config import get_settings
from app.db.session import get_session
from app.models import AppUser, Customer, UserRole


@dataclass(frozen=True)
class RequestActor:
    app_user_id: UUID
    telegram_user_id: int
    role: UserRole
    customer_id: UUID | None

    def require_customer_access(self, customer_id: UUID) -> None:
        if self.role not in {UserRole.ADMIN, UserRole.VIEWER} and self.customer_id != customer_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    def require_staff(self) -> None:
        if self.role not in {UserRole.ADMIN, UserRole.VIEWER}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")

    def require_admin(self) -> None:
        if self.role is not UserRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    def require_customer(self) -> None:
        if self.role is not UserRole.CUSTOMER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer access required")


async def get_request_actor(
    init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> RequestActor:
    settings = get_settings()
    try:
        identity = validate_init_data(
            init_data or "",
            settings.telegram_bot_token,
            settings.telegram_init_data_max_age_seconds,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user = await session.scalar(
        select(AppUser).where(AppUser.telegram_user_id == identity.telegram_user_id)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not registered")
    customer_id = await session.scalar(
        select(Customer.id).where(Customer.app_user_id == user.id)
    )
    return RequestActor(user.id, user.telegram_user_id, user.role, customer_id)
