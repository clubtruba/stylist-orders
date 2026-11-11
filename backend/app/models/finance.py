import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ServiceFeeType(str, enum.Enum):
    FIXED = "FIXED"
    PERCENTAGE_RESULT = "PERCENTAGE_RESULT"
    MANUAL = "MANUAL"
    OTHER = "OTHER"


class ReturnStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    SENT_TO_MERCHANT = "SENT_TO_MERCHANT"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


class ServiceFee(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "service_fees"
    customer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), index=True)
    shipment_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("customer_shipments.id", ondelete="RESTRICT"), index=True)
    fee_type: Mapped[ServiceFeeType] = mapped_column(Enum(ServiceFeeType, name="service_fee_type"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("amount >= 0", name="non_negative_amount"),)


class Payment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    customer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    shipment_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("customer_shipments.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    method: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reversed_payment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )
    __table_args__ = (CheckConstraint("amount <> 0", name="non_zero_amount"),)


class PaymentEvidence(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payment_evidence"
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    submitted_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_users.id", ondelete="RESTRICT"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    stored_filename: Mapped[str | None] = mapped_column(String(255), unique=True)
    telegram_file_id: Mapped[str | None] = mapped_column(Text)
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        CheckConstraint(
            "note IS NOT NULL OR stored_filename IS NOT NULL",
            name="note_or_file_required",
        ),
    )


class ItemReturn(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "item_returns"
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("items.id", ondelete="RESTRICT"), index=True)
    status: Mapped[ReturnStatus] = mapped_column(Enum(ReturnStatus, name="return_status"), index=True)
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
