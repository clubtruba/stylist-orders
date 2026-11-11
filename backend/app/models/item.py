import enum
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ItemStatus(str, enum.Enum):
    TO_BUY = "TO_BUY"
    ORDERED = "ORDERED"
    PURCHASED_OFFLINE = "PURCHASED_OFFLINE"
    ON_THE_WAY_TO_US = "ON_THE_WAY_TO_US"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    RECEIVED = "RECEIVED"
    ASSIGNED_TO_SHIPMENT = "ASSIGNED_TO_SHIPMENT"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURN_IN_PROGRESS = "RETURN_IN_PROGRESS"
    RETURNED = "RETURNED"


class Item(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "items"

    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    product_url: Mapped[str] = mapped_column(Text)
    size: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    customer_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus, name="item_status"), index=True)
    listed_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    listed_currency: Mapped[str | None] = mapped_column(String(3))
