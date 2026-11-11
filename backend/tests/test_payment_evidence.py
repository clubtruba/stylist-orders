import pytest

from app.db.session import SessionFactory
from app.models import AppUser, CollectionStatus, Customer, Item, ItemStatus, UserRole
from app.services.payment_evidence import PaymentEvidenceError, PaymentEvidenceService


@pytest.mark.asyncio
async def test_admin_can_add_text_payment_evidence(tmp_path):
    async with SessionFactory() as session:
        async with session.begin():
            admin = AppUser(
                telegram_user_id=9_000_000_201,
                role=UserRole.ADMIN,
                first_name="Payment Admin",
            )
            customer_user = AppUser(
                telegram_user_id=9_000_000_202,
                role=UserRole.CUSTOMER,
                first_name="Payment Customer",
            )
            session.add_all([admin, customer_user])
            await session.flush()
            customer = Customer(
                app_user_id=customer_user.id,
                display_name="Payment Customer",
                collection_status=CollectionStatus.COLLECTING,
                financial_details_visible=False,
            )
            session.add(customer)
            await session.flush()
            item = Item(
                customer_id=customer.id,
                product_url="https://example.com/paid-item",
                quantity=1,
                status=ItemStatus.TO_BUY,
            )
            session.add(item)
            await session.flush()

            evidence = await PaymentEvidenceService(session, str(tmp_path)).create(
                item.id,
                admin.id,
                admin=True,
                note="Paid by bank transfer",
            )
            assert evidence.note == "Paid by bank transfer"
            assert evidence.stored_filename is None
            await session.rollback()


def test_payment_image_rejects_unsupported_type(tmp_path):
    service = PaymentEvidenceService(None, str(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(PaymentEvidenceError, match="JPEG"):
        service.save_image(b"not-an-image", "application/pdf", "receipt.pdf")
