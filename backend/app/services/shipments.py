from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CustomerAddress,
    Customer,
    CustomerShipment,
    AuditLog,
    Item,
    ItemStatus,
    ItemStatusHistory,
    ShipmentItem,
    ShipmentStatus,
    NotificationOutbox,
)


class ShipmentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CreateShipmentCommand:
    customer_id: UUID
    address_id: UUID
    item_ids: tuple[UUID, ...]
    actor_user_id: UUID
    currency: str = "EUR"


class ShipmentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, command: CreateShipmentCommand) -> CustomerShipment:
        if not command.item_ids:
            raise ShipmentValidationError("shipment requires at least one item")
        if len(set(command.item_ids)) != len(command.item_ids):
            raise ShipmentValidationError("duplicate item ids are not allowed")
        if len(command.currency) != 3:
            raise ShipmentValidationError("currency must be an ISO 4217 code")

        address = await self.session.scalar(
            select(CustomerAddress)
            .where(
                CustomerAddress.id == command.address_id,
                CustomerAddress.customer_id == command.customer_id,
            )
            .with_for_update()
        )
        if address is None:
            raise ShipmentValidationError("address does not belong to customer")

        items = list(
            (
                await self.session.scalars(
                    select(Item).where(Item.id.in_(command.item_ids)).with_for_update()
                )
            ).all()
        )
        if len(items) != len(command.item_ids):
            raise ShipmentValidationError("one or more items do not exist")
        if any(item.customer_id != command.customer_id for item in items):
            raise ShipmentValidationError("all items must belong to the shipment customer")
        eligible = {ItemStatus.PURCHASED_OFFLINE, ItemStatus.RECEIVED}
        if any(item.status not in eligible for item in items):
            raise ShipmentValidationError("only warehouse items can be assigned")

        shipment = CustomerShipment(
            customer_id=command.customer_id,
            status=ShipmentStatus.PREPARING,
            currency=command.currency.upper(),
            shipping_cost=Decimal("0"),
            packaging_cost=Decimal("0"),
            insurance_cost=Decimal("0"),
            customs_fee=Decimal("0"),
            other_fee=Decimal("0"),
            address_recipient_name=address.recipient_name,
            address_phone=address.phone,
            address_country_code=address.country_code,
            address_postal_code=address.postal_code,
            address_region=address.region,
            address_city=address.city,
            address_line1=address.address_line1,
            address_line2=address.address_line2,
        )
        self.session.add(shipment)
        await self.session.flush()

        for item in items:
            previous = item.status
            item.status = ItemStatus.ASSIGNED_TO_SHIPMENT
            self.session.add(ShipmentItem(shipment_id=shipment.id, item_id=item.id))
            self.session.add(
                ItemStatusHistory(
                    item_id=item.id,
                    from_status=previous,
                    to_status=ItemStatus.ASSIGNED_TO_SHIPMENT,
                    changed_by_user_id=command.actor_user_id,
                    reason=f"assigned to shipment {shipment.id}",
                )
            )
        self.session.add(
            AuditLog(
                actor_user_id=command.actor_user_id,
                action="SHIPMENT_CREATED",
                entity_type="CustomerShipment",
                entity_id=shipment.id,
                payload={
                    "customer_id": str(command.customer_id),
                    "address_id": str(command.address_id),
                    "item_ids": [str(item.id) for item in items],
                },
            )
        )
        await self.session.flush()
        return shipment

    async def dispatch(
        self,
        shipment_id: UUID,
        carrier: str,
        tracking_number: str,
        actor_user_id: UUID,
    ) -> CustomerShipment:
        shipment = await self.session.scalar(
            select(CustomerShipment)
            .where(CustomerShipment.id == shipment_id)
            .with_for_update()
        )
        if shipment is None:
            raise ShipmentValidationError("shipment not found")
        if shipment.status is not ShipmentStatus.PREPARING:
            raise ShipmentValidationError("only preparing shipment can be dispatched")
        links = list((await self.session.scalars(
            select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id)
        )).all())
        if not links:
            raise ShipmentValidationError("shipment has no items")
        if len(carrier.strip()) < 2 or len(tracking_number.strip()) < 3:
            raise ShipmentValidationError("carrier and tracking number are required")
        items = list((await self.session.scalars(
            select(Item).where(Item.id.in_([link.item_id for link in links])).with_for_update()
        )).all())
        shipment.carrier = carrier.strip()
        shipment.tracking_number = tracking_number.strip()
        shipment.status = ShipmentStatus.SHIPPED
        shipment.shipped_at = datetime.now(timezone.utc)
        recipient_user_id = await self.session.scalar(
            select(Customer.app_user_id).where(Customer.id == shipment.customer_id)
        )
        for item in items:
            previous = item.status
            item.status = ItemStatus.SHIPPED
            self.session.add(ItemStatusHistory(
                item_id=item.id,
                from_status=previous,
                to_status=ItemStatus.SHIPPED,
                changed_by_user_id=actor_user_id,
                reason=f"shipment {shipment.id}; tracking {shipment.tracking_number}",
            ))
            if recipient_user_id is not None:
                self.session.add(NotificationOutbox(
                    recipient_user_id=recipient_user_id,
                    event_type="ITEM_STATUS_CHANGED",
                    payload={
                        "item_id": str(item.id),
                        "from": previous.value,
                        "to": ItemStatus.SHIPPED.value,
                        "tracking_number": shipment.tracking_number,
                    },
                ))
        self.session.add(AuditLog(
            actor_user_id=actor_user_id,
            action="SHIPMENT_DISPATCHED",
            entity_type="CustomerShipment",
            entity_id=shipment.id,
            payload={
                "carrier": shipment.carrier,
                "tracking_number": shipment.tracking_number,
                "item_ids": [str(item.id) for item in items],
            },
        ))
        await self.session.flush()
        return shipment

    async def save_tracking_for_shipped_item(
        self,
        item_id: UUID,
        carrier: str,
        tracking_number: str,
        actor_user_id: UUID,
    ) -> CustomerShipment:
        carrier = carrier.strip()
        tracking_number = tracking_number.strip()
        if len(carrier) < 2 or len(tracking_number) < 3:
            raise ShipmentValidationError("carrier and tracking number are required")
        item = await self.session.scalar(
            select(Item).where(Item.id == item_id).with_for_update()
        )
        if item is None:
            raise ShipmentValidationError("item not found")
        if item.status is not ItemStatus.SHIPPED:
            raise ShipmentValidationError("tracking can only be saved for a shipped item")
        shipment = await self.session.scalar(
            select(CustomerShipment)
            .join(ShipmentItem, ShipmentItem.shipment_id == CustomerShipment.id)
            .where(ShipmentItem.item_id == item.id)
            .with_for_update()
        )
        if shipment is None:
            address = await self.session.scalar(select(CustomerAddress).where(
                CustomerAddress.customer_id == item.customer_id,
                CustomerAddress.is_default.is_(True),
            ))
            if address is None:
                raise ShipmentValidationError("customer has no address")
            shipment = CustomerShipment(
                customer_id=item.customer_id,
                status=ShipmentStatus.SHIPPED,
                currency="EUR",
                shipping_cost=Decimal("0"),
                packaging_cost=Decimal("0"),
                insurance_cost=Decimal("0"),
                customs_fee=Decimal("0"),
                other_fee=Decimal("0"),
                shipped_at=datetime.now(timezone.utc),
                address_recipient_name=address.recipient_name,
                address_phone=address.phone,
                address_country_code=address.country_code,
                address_postal_code=address.postal_code,
                address_region=address.region,
                address_city=address.city,
                address_line1=address.address_line1,
                address_line2=address.address_line2,
            )
            self.session.add(shipment)
            await self.session.flush()
            self.session.add(ShipmentItem(shipment_id=shipment.id, item_id=item.id))
        shipment.carrier = carrier
        shipment.tracking_number = tracking_number
        recipient_user_id = await self.session.scalar(
            select(Customer.app_user_id).where(Customer.id == item.customer_id)
        )
        if recipient_user_id is not None:
            self.session.add(NotificationOutbox(
                recipient_user_id=recipient_user_id,
                event_type="SHIPMENT_TRACKING_UPDATED",
                payload={
                    "item_id": str(item.id),
                    "carrier": carrier,
                    "tracking_number": tracking_number,
                },
            ))
        self.session.add(AuditLog(
            actor_user_id=actor_user_id,
            action="SHIPMENT_TRACKING_UPDATED",
            entity_type="CustomerShipment",
            entity_id=shipment.id,
            payload={
                "item_id": str(item.id),
                "carrier": carrier,
                "tracking_number": tracking_number,
            },
        ))
        await self.session.flush()
        return shipment
