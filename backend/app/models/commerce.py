import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class CollectionStatus(str, enum.Enum):
    COLLECTING = "COLLECTING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPMENT_REQUESTED = "SHIPMENT_REQUESTED"


class AllocationMethod(str, enum.Enum):
    EQUAL = "EQUAL"
    PROPORTIONAL_BY_VALUE = "PROPORTIONAL_BY_VALUE"
    MANUAL = "MANUAL"
    UNALLOCATED = "UNALLOCATED"


class ShipmentStatus(str, enum.Enum):
    PREPARING = "PREPARING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Customer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    app_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"), unique=True
    )
    display_name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    internal_note: Mapped[str | None] = mapped_column(Text)
    collection_status: Mapped[CollectionStatus] = mapped_column(
        Enum(CollectionStatus, name="collection_status"), default=CollectionStatus.COLLECTING
    )
    financial_details_visible: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomerAddress(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "customer_addresses"
    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(100))
    recipient_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    country_code: Mapped[str] = mapped_column(String(2))
    postal_code: Mapped[str] = mapped_column(String(32))
    region: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(200))
    address_line1: Mapped[str] = mapped_column(String(300))
    address_line2: Mapped[str | None] = mapped_column(String(300))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index(
            "uq_customer_addresses_one_default",
            "customer_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class Merchant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "merchants"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True)


class MerchantPurchase(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "merchant_purchases"
    merchant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id", ondelete="RESTRICT"), index=True
    )
    external_order_number: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    merchant_shipping_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    merchant_discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    other_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    allocation_method: Mapped[AllocationMethod] = mapped_column(
        Enum(AllocationMethod, name="allocation_method"), default=AllocationMethod.EQUAL
    )
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("char_length(currency) = 3", name="currency_iso_length"),)


class MerchantPurchaseItem(UUIDMixin, Base):
    __tablename__ = "merchant_purchase_items"
    purchase_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchant_purchases.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), unique=True
    )
    actual_purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    allocated_shipping: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    allocated_discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))


class MerchantDelivery(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "merchant_deliveries"
    purchase_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchant_purchases.id", ondelete="CASCADE"), index=True
    )
    carrier: Mapped[str | None] = mapped_column(String(100))
    tracking_number: Mapped[str | None] = mapped_column(String(200))
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MerchantDeliveryItem(UUIDMixin, Base):
    __tablename__ = "merchant_delivery_items"
    delivery_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchant_deliveries.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), index=True
    )
    __table_args__ = (Index("uq_merchant_delivery_items", "delivery_id", "item_id", unique=True),)


class CustomerShipment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "customer_shipments"
    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[ShipmentStatus] = mapped_column(Enum(ShipmentStatus, name="shipment_status"), index=True)
    carrier: Mapped[str | None] = mapped_column(String(100))
    tracking_number: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    packaging_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    insurance_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    customs_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    other_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    address_recipient_name: Mapped[str] = mapped_column(String(200))
    address_phone: Mapped[str | None] = mapped_column(String(50))
    address_country_code: Mapped[str] = mapped_column(String(2))
    address_postal_code: Mapped[str] = mapped_column(String(32))
    address_region: Mapped[str | None] = mapped_column(String(200))
    address_city: Mapped[str] = mapped_column(String(200))
    address_line1: Mapped[str] = mapped_column(String(300))
    address_line2: Mapped[str | None] = mapped_column(String(300))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShipmentItem(UUIDMixin, Base):
    __tablename__ = "shipment_items"
    shipment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customer_shipments.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), unique=True
    )
