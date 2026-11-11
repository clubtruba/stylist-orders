"""drafts, immutable history, audit, outbox and idempotency"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_operational_guards"
down_revision = "0001_bootstrap"
branch_labels = None
depends_on = None

draft_status = postgresql.ENUM("OPEN", "CONFIRMED", "CANCELLED", "EXPIRED", name="draft_status", create_type=False)
outbox_status = postgresql.ENUM("PENDING", "PROCESSING", "SENT", "FAILED", name="outbox_status", create_type=False)
item_status = postgresql.ENUM("TO_BUY", "ORDERED", "PURCHASED_OFFLINE", "ON_THE_WAY_TO_US", "READY_FOR_PICKUP", "RECEIVED", "ASSIGNED_TO_SHIPMENT", "SHIPPED", "DELIVERED", "CANCELLED", "RETURN_IN_PROGRESS", "RETURNED", name="item_status", create_type=False)


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade():
    draft_status.create(op.get_bind(), checkfirst=True)
    outbox_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "item_drafts",
        sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("product_url", sa.Text(), nullable=False),
        sa.Column("size", sa.String(64)), sa.Column("color", sa.String(128)),
        sa.Column("quantity", sa.Integer(), nullable=False), sa.Column("customer_note", sa.Text()),
        sa.Column("status", draft_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), *timestamps(),
        sa.ForeignKeyConstraint(["customer_user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_item_drafts"),
    )
    op.create_index("ix_item_drafts_customer_user_id", "item_drafts", ["customer_user_id"])
    op.create_index("ix_item_drafts_status", "item_drafts", ["status"])
    op.create_index("uq_item_drafts_private_message", "item_drafts", ["telegram_chat_id", "telegram_message_id"], unique=True)
    op.create_table(
        "item_status_history",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", item_status), sa.Column("to_status", item_status, nullable=False),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text()), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["app_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_item_status_history"),
    )
    op.create_index("ix_item_status_history_item_id", "item_status_history", ["item_id"])
    op.create_table(
        "audit_logs",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)), sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False), sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    for name, cols in (("ix_audit_logs_actor_user_id", ["actor_user_id"]), ("ix_audit_logs_action", ["action"]), ("ix_audit_logs_entity_id", ["entity_id"])):
        op.create_index(name, "audit_logs", cols)
    op.create_table(
        "notification_outbox",
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", outbox_status, nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text()), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), *timestamps(),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_notification_outbox"),
    )
    for name, cols in (("ix_notification_outbox_recipient_user_id", ["recipient_user_id"]), ("ix_notification_outbox_status", ["status"]), ("ix_notification_outbox_available_at", ["available_at"])):
        op.create_index(name, "notification_outbox", cols)
    op.create_table(
        "idempotency_keys",
        sa.Column("scope", sa.String(100), nullable=False), sa.Column("key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("response_code", sa.Integer()),
        sa.Column("response_payload", sa.JSON()), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_keys"),
    )
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])
    op.create_index("uq_idempotency_keys_scope_key", "idempotency_keys", ["scope", "key"], unique=True)


def downgrade():
    for table in ("idempotency_keys", "notification_outbox", "audit_logs", "item_status_history", "item_drafts"):
        op.drop_table(table)
    outbox_status.drop(op.get_bind(), checkfirst=True)
    draft_status.drop(op.get_bind(), checkfirst=True)
