import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models import CustomerAddress, DraftStatus, Item, ItemDraft, UserRole
from app.services.drafts import DraftError, DraftService, OpenDraftCommand
from app.services.users import UserService


@pytest.mark.asyncio
async def test_parallel_drafts_remain_isolated_and_duplicate_confirmation_is_blocked():
    async with SessionFactory() as session:
        async with session.begin():
            user, customer = await UserService(session).register_customer(
                9_000_000_002, "Parallel", "Customer", "parallel_customer"
            )
            customer.phone = "+37255550000"
            session.add(CustomerAddress(
                customer_id=customer.id,
                label="Home",
                recipient_name="Parallel Customer",
                phone=customer.phone,
                country_code="EE",
                postal_code="10111",
                city="Tallinn",
                address_line1="Test street 1",
                is_default=True,
            ))
            await session.flush()
            service = DraftService(session)
            first = await service.open(OpenDraftCommand(user.id, 9_000_000_002, 101, "https://example.com/a"))
            second = await service.open(OpenDraftCommand(user.id, 9_000_000_002, 102, "https://example.com/b"))
            repeated = await service.open(OpenDraftCommand(user.id, 9_000_000_002, 101, "https://example.com/a"))
            assert repeated.id == first.id

            await service.set_size(first.id, user.id, "M")
            await service.set_size(second.id, user.id, "S")
            await service.set_comment(first.id, user.id, "Please use secure packaging")
            item = await service.confirm(first.id, user.id, customer.id)
            await session.flush()

            assert item.size == "M"
            assert item.customer_note == "Please use secure packaging"
            assert first.status is DraftStatus.CONFIRMED
            assert second.status is DraftStatus.OPEN
            assert await session.scalar(select(Item).where(Item.id == item.id))
            assert await session.scalar(select(ItemDraft).where(ItemDraft.id == second.id))
            with pytest.raises(DraftError, match="no longer open"):
                await service.confirm(first.id, user.id, customer.id)

            await session.rollback()


@pytest.mark.asyncio
async def test_confirmation_requires_complete_delivery_profile():
    async with SessionFactory() as session:
        async with session.begin():
            user, customer = await UserService(session).register_customer(
                9_000_000_003, "Missing", "Profile", "missing_profile"
            )
            service = DraftService(session)
            draft = await service.open(OpenDraftCommand(
                user.id, 9_000_000_003, 103, "https://example.com/profile-required"
            ))
            with pytest.raises(DraftError, match="заполните"):
                await service.confirm(draft.id, user.id, customer.id)
            await session.rollback()


@pytest.mark.asyncio
async def test_viewer_cannot_modify_existing_draft():
    async with SessionFactory() as session:
        async with session.begin():
            user, _ = await UserService(session).register_customer(
                9_000_000_004, "Read", "Only", "read_only"
            )
            service = DraftService(session)
            draft = await service.open(OpenDraftCommand(
                user.id, 9_000_000_004, 104, "https://example.com/read-only"
            ))
            user.role = UserRole.VIEWER
            await session.flush()
            with pytest.raises(DraftError, match="только для просмотра"):
                await service.set_size(draft.id, user.id, "M")
            await session.rollback()
