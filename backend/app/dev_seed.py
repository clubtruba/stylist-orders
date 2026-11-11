import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import AppUser, Customer, Item, ItemStatus, UserRole
from app.services.users import UserService

ADMIN_TELEGRAM_ID = 9_100_000_001
CUSTOMER_TELEGRAM_ID = 9_100_000_002


def signed_init_data(telegram_user_id: int, first_name: str, username: str, token: str) -> str:
    fields = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": f"dev-{telegram_user_id}",
        "user": json.dumps(
            {"id": telegram_user_id, "first_name": first_name, "username": username},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def seed() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Development seed is forbidden in production")
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for signed local sessions")
    async with SessionFactory() as session, session.begin():
        admin = await session.scalar(
            select(AppUser).where(AppUser.telegram_user_id == ADMIN_TELEGRAM_ID)
        )
        if admin is None:
            admin = AppUser(
                telegram_user_id=ADMIN_TELEGRAM_ID,
                role=UserRole.ADMIN,
                username="local_admin",
                first_name="Local",
                last_name="Admin",
            )
            session.add(admin)
        customer_user, customer = await UserService(session).register_customer(
            CUSTOMER_TELEGRAM_ID, "Наталья", "Тестовая", "local_customer"
        )
        await add_sample_items(session, customer)

    admin_data = signed_init_data(ADMIN_TELEGRAM_ID, "Local", "local_admin", settings.telegram_bot_token)
    customer_data = signed_init_data(
        CUSTOMER_TELEGRAM_ID, "Наталья", "local_customer", settings.telegram_bot_token
    )
    print("ADMIN_URL=http://127.0.0.1:5173/?" + urlencode({"dev_init_data": admin_data}))
    print("CUSTOMER_URL=http://127.0.0.1:5173/?" + urlencode({"dev_init_data": customer_data}))


async def add_sample_items(session, customer: Customer) -> None:
    exists = await session.scalar(select(Item.id).where(Item.customer_id == customer.id).limit(1))
    if exists is not None:
        return
    session.add_all(
        [
            Item(customer_id=customer.id, product_url="https://www.zara.com/example-dress",
                 size="M", color="Black", quantity=1, status=ItemStatus.TO_BUY),
            Item(customer_id=customer.id, product_url="https://shop.mango.com/example-skirt",
                 size="S", color="Blue", quantity=1, status=ItemStatus.ON_THE_WAY_TO_US),
            Item(customer_id=customer.id, product_url="https://www.massimodutti.com/example-shirt",
                 size="L", color="White", quantity=1, status=ItemStatus.RECEIVED),
        ]
    )


if __name__ == "__main__":
    asyncio.run(seed())
