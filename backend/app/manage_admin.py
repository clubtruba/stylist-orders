import argparse
import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import AppUser, AuditLog, UserRole


async def promote(telegram_user_id: int) -> None:
    settings = get_settings()
    if telegram_user_id not in settings.telegram_admin_id_set:
        raise SystemExit("Telegram ID is not present in TELEGRAM_ADMIN_IDS")
    async with SessionFactory() as session, session.begin():
        user = await session.scalar(
            select(AppUser)
            .where(AppUser.telegram_user_id == telegram_user_id)
            .with_for_update()
        )
        if user is None:
            raise SystemExit("User must send /start to the bot before promotion")
        previous_role = user.role
        if previous_role is UserRole.ADMIN:
            print("User is already ADMIN; no change made")
            return
        user.role = UserRole.ADMIN
        session.add(
            AuditLog(
                actor_user_id=user.id,
                action="ADMIN_ROLE_GRANTED",
                entity_type="AppUser",
                entity_id=user.id,
                payload={
                    "telegram_user_id": telegram_user_id,
                    "from_role": previous_role.value,
                    "to_role": UserRole.ADMIN.value,
                    "source": "TELEGRAM_ADMIN_IDS bootstrap",
                },
            )
        )
    print(f"Telegram user {telegram_user_id} promoted to ADMIN with audit record")


async def grant_viewer(telegram_user_id: int) -> None:
    async with SessionFactory() as session, session.begin():
        user = await session.scalar(
            select(AppUser)
            .where(AppUser.telegram_user_id == telegram_user_id)
            .with_for_update()
        )
        if user is None:
            raise SystemExit("User must send /start to the bot before VIEWER access is granted")
        previous_role = user.role
        if previous_role is UserRole.ADMIN:
            raise SystemExit("Refusing to replace ADMIN role with VIEWER")
        if previous_role is UserRole.VIEWER:
            print("User is already VIEWER; no change made")
            return
        user.role = UserRole.VIEWER
        session.add(
            AuditLog(
                actor_user_id=user.id,
                action="VIEWER_ROLE_GRANTED",
                entity_type="AppUser",
                entity_id=user.id,
                payload={
                    "telegram_user_id": telegram_user_id,
                    "from_role": previous_role.value,
                    "to_role": UserRole.VIEWER.value,
                    "source": "manage_admin command",
                },
            )
        )
    print(f"Telegram user {telegram_user_id} granted VIEWER access with audit record")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Telegram Orders staff roles")
    parser.add_argument("action", choices=["promote", "grant-viewer"])
    parser.add_argument("--telegram-id", type=int, required=True)
    args = parser.parse_args()
    action = promote if args.action == "promote" else grant_viewer
    asyncio.run(action(args.telegram_id))


if __name__ == "__main__":
    main()
