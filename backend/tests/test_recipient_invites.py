from uuid import uuid4

import pytest

from app.db.session import SessionFactory
from app.models import AppUser, Customer, UserRole
from app.services.orders import OrderError
from app.services.recipient_invites import create_invite, redeem_invite


@pytest.mark.asyncio
async def test_invite_is_single_use_and_links_only_recipient():
    async with SessionFactory() as session:
        stylist = AppUser(
            telegram_user_id=uuid4().int % 10**14, first_name="Stylist", role=UserRole.CUSTOMER
        )
        session.add(stylist)
        await session.flush()
        customer = Customer(stylist_id=stylist.id, display_name="IVAN IVANOV")
        session.add(customer)
        await session.flush()
        url = await create_invite(session, customer)
        await session.flush()
        token = url.split("recv_")[1]
        linked = await redeem_invite(
            session, token, uuid4().int % 10**14, "Recipient", None, "recipient"
        )
        assert linked.app_user_id is not None and linked.stylist_id == stylist.id
        with pytest.raises(OrderError):
            await redeem_invite(session, token, 99999, "Other", None, None)
        await session.rollback()
