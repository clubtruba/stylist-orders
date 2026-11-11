"""Order-level records for the stylist workflow; legacy item statuses are reused."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class StylistOrder(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "stylist_orders"
    number: Mapped[str] = mapped_column(String(24), unique=True)
    stylist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_users.id"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id"), index=True
    )
    address_snapshot: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    intake_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    active_quote_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    __table_args__ = (
        CheckConstraint(
            "state IN ('DRAFT','AWAITING_PAYMENT','SUBMITTED','CANCELLED')",
            name="valid_order_state",
        ),
    )


class OrderQuote(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "order_quotes"
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stylist_orders.id"), index=True
    )
    rate_date: Mapped[date] = mapped_column(Date)
    eur_rub_rate: Mapped[Decimal] = mapped_column(Numeric(16, 6))
    goods_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    due_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    close_order: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(16), default="ISSUED")
    __table_args__ = (
        CheckConstraint("due_rub > 0", name="positive_quote_amount"),
        CheckConstraint("state IN ('ISSUED','PAID','VOID')", name="valid_quote_state"),
    )


class QuoteLine(UUIDMixin, Base):
    __tablename__ = "order_quote_lines"
    quote_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("order_quotes.id"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("items.id"), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class OrderPayment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "order_payments"
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stylist_orders.id"), index=True
    )
    quote_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("order_quotes.id"), unique=True
    )
    screenshot_file_id: Mapped[str] = mapped_column(String(512))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id", "telegram_message_id", name="uq_order_payment_message"
        ),
    )


class OrderRefund(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "order_refunds"
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stylist_orders.id"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("items.id"), unique=True)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(String(1000))
    state: Mapped[str] = mapped_column(String(16), default="PENDING")
    __table_args__ = (
        CheckConstraint("state IN ('PENDING','REFUNDED')", name="valid_refund_state"),
    )


class ExchangeRate(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "exchange_rates"
    business_date: Mapped[date] = mapped_column(Date, unique=True)
    effective_date: Mapped[date] = mapped_column(Date)
    eur_rub: Mapped[Decimal] = mapped_column(Numeric(16, 6))
    __table_args__ = (CheckConstraint("eur_rub > 0", name="positive_rate"),)


class BotConversation(Base):
    __tablename__ = "bot_conversations"
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="IDLE")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    active_order_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stylist_orders.id")
    )


class RecipientInvite(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "recipient_invites"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
