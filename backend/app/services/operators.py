from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AppUser, UserRole


def operator_role(telegram_id: int) -> UserRole:
    settings = get_settings()
    if telegram_id in settings.telegram_admin_id_set:
        return UserRole.ADMIN
    if telegram_id in settings.telegram_stylist_id_set:
        # Keep the existing database enum; CUSTOMER is an intake operator here.
        return UserRole.CUSTOMER
    raise PermissionError("Доступ к оформлению заказов не разрешен")


async def register_operator(
    session: AsyncSession,
    telegram_id: int,
    first_name: str,
    last_name: str | None,
    username: str | None,
) -> AppUser:
    role = operator_role(telegram_id)
    from sqlalchemy.dialects.postgresql import insert

    await session.execute(
        insert(AppUser)
        .values(
            telegram_user_id=telegram_id,
            role=role,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        .on_conflict_do_update(
            index_elements=["telegram_user_id"],
            set_={
                "role": role,
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
            },
        )
    )
    return (
        await session.scalars(select(AppUser).where(AppUser.telegram_user_id == telegram_id))
    ).one()
