from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, CollectionStatus, Customer, CustomerAddress, UserRole


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def register_customer(self, telegram_user_id: int, first_name: str,
                                last_name: str | None, username: str | None) -> tuple[AppUser, Customer]:
        user = await self.session.scalar(select(AppUser).where(
            AppUser.telegram_user_id == telegram_user_id).with_for_update())
        if user is None:
            user = AppUser(telegram_user_id=telegram_user_id, role=UserRole.CUSTOMER,
                           first_name=first_name, last_name=last_name, username=username)
            self.session.add(user)
            await self.session.flush()
        else:
            user.first_name, user.last_name, user.username = first_name, last_name, username
        customer = await self.session.scalar(select(Customer).where(
            Customer.app_user_id == user.id).with_for_update())
        if customer is None:
            customer = Customer(app_user_id=user.id,
                display_name=" ".join(v for v in (first_name, last_name) if v),
                collection_status=CollectionStatus.COLLECTING, financial_details_visible=False)
            self.session.add(customer)
            await self.session.flush()
        return user, customer

    async def has_complete_delivery_profile(self, customer_id) -> bool:
        customer = await self.session.get(Customer, customer_id)
        if customer is None or not customer.phone:
            return False
        address_id = await self.session.scalar(select(CustomerAddress.id).where(
            CustomerAddress.customer_id == customer_id,
            CustomerAddress.is_default.is_(True),
        ))
        return address_id is not None
