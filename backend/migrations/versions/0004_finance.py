"""service fees, payments and returns"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_finance"
down_revision = "0003_commerce"
branch_labels = None
depends_on = None
UUID = postgresql.UUID(as_uuid=True)
fee_type = postgresql.ENUM("FIXED", "PERCENTAGE_RESULT", "MANUAL", "OTHER", name="service_fee_type", create_type=False)
return_status = postgresql.ENUM("REQUESTED", "SENT_TO_MERCHANT", "REFUND_PENDING", "REFUNDED", "REJECTED", name="return_status", create_type=False)


def common():
    return [sa.Column("id", UUID, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    fee_type.create(op.get_bind(), checkfirst=True)
    return_status.create(op.get_bind(), checkfirst=True)
    op.create_table("service_fees",
        sa.Column("customer_id", UUID, nullable=False), sa.Column("item_id", UUID), sa.Column("shipment_id", UUID),
        sa.Column("fee_type", fee_type, nullable=False), sa.Column("amount", sa.Numeric(14,2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("note", sa.Text()), *common(),
        sa.CheckConstraint("amount >= 0", name="ck_service_fees_non_negative_amount"),
        sa.ForeignKeyConstraint(["customer_id"],["customers.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["item_id"],["items.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"],["customer_shipments.id"],ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"))
    op.create_table("payments",
        sa.Column("customer_id", UUID, nullable=False), sa.Column("shipment_id", UUID),
        sa.Column("amount", sa.Numeric(14,2), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(100)), sa.Column("note", sa.Text()),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False), sa.Column("reversed_payment_id", UUID), *common(),
        sa.CheckConstraint("amount <> 0", name="ck_payments_non_zero_amount"),
        sa.ForeignKeyConstraint(["customer_id"],["customers.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"],["customer_shipments.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversed_payment_id"],["payments.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("reversed_payment_id"))
    op.create_table("item_returns",
        sa.Column("item_id", UUID, nullable=False), sa.Column("status", return_status, nullable=False),
        sa.Column("refund_amount", sa.Numeric(14,2)), sa.Column("currency", sa.String(3)),
        sa.Column("reason", sa.Text()), sa.Column("completed_at", sa.DateTime(timezone=True)), *common(),
        sa.ForeignKeyConstraint(["item_id"],["items.id"],ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"))
    for table, columns in {
        "service_fees": ("customer_id","item_id","shipment_id"),
        "payments": ("customer_id","shipment_id"),
        "item_returns": ("item_id","status"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("item_returns", "payments", "service_fees"):
        op.drop_table(table)
    return_status.drop(op.get_bind(), checkfirst=True)
    fee_type.drop(op.get_bind(), checkfirst=True)
