import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models import (
    AppUser,
    AuditLog,
    CollectionStatus,
    Customer,
    Item,
    ItemStatus,
    ItemStatusHistory,
    NotificationOutbox,
    UserRole,
)
from app.services.items import ItemService


@pytest.mark.asyncio
async def test_admin_transition_records_history_and_notification():
    async with SessionFactory() as session:
        async with session.begin():
            admin = AppUser(
                telegram_user_id=9_000_000_101,
                role=UserRole.ADMIN,
                first_name="Workflow",
            )
            customer_user = AppUser(
                telegram_user_id=9_000_000_102,
                role=UserRole.CUSTOMER,
                first_name="Customer",
            )
            session.add_all([admin, customer_user])
            await session.flush()
            customer = Customer(
                app_user_id=customer_user.id,
                display_name="Workflow Customer",
                collection_status=CollectionStatus.COLLECTING,
                financial_details_visible=False,
            )
            session.add(customer)
            await session.flush()
            item = Item(
                customer_id=customer.id,
                product_url="https://example.com/workflow-item",
                quantity=1,
                status=ItemStatus.TO_BUY,
            )
            session.add(item)
            await session.flush()

            await ItemService(session).transition(
                item.id, ItemStatus.ORDERED, admin.id, "Purchased by administrator"
            )

            history = await session.scalar(
                select(ItemStatusHistory).where(ItemStatusHistory.item_id == item.id)
            )
            notification = await session.scalar(
                select(NotificationOutbox).where(
                    NotificationOutbox.recipient_user_id == customer_user.id
                )
            )
            assert item.status is ItemStatus.ORDERED
            assert history is not None
            assert history.reason == "Purchased by administrator"
            assert notification is not None
            assert notification.payload["to"] == ItemStatus.ORDERED.value

            await ItemService(session).correct_status(
                item.id, ItemStatus.RECEIVED, admin.id, "Incorrect manual status"
            )
            audit = await session.scalar(
                select(AuditLog).where(
                    AuditLog.entity_id == item.id,
                    AuditLog.action == "ITEM_STATUS_CORRECTED",
                )
            )
            assert item.status is ItemStatus.RECEIVED
            assert audit is not None
            assert audit.payload["reason"] == "Incorrect manual status"

            await session.rollback()
