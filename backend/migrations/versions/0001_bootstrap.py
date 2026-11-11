"""bootstrap users and items"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_bootstrap"
down_revision = None
branch_labels = None
depends_on = None

user_role = postgresql.ENUM("ADMIN", "CUSTOMER", name="user_role", create_type=False)
item_status = postgresql.ENUM("TO_BUY", "ORDERED", "PURCHASED_OFFLINE", "ON_THE_WAY_TO_US",
    "READY_FOR_PICKUP", "RECEIVED", "ASSIGNED_TO_SHIPMENT", "SHIPPED", "DELIVERED",
    "CANCELLED", "RETURN_IN_PROGRESS", "RETURNED", name="item_status", create_type=False)

def upgrade():
    user_role.create(op.get_bind(), checkfirst=True)
    item_status.create(op.get_bind(), checkfirst=True)
    op.create_table("app_users", sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", user_role, nullable=False), sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128), nullable=False), sa.Column("last_name", sa.String(128)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_users"),
        sa.UniqueConstraint("telegram_user_id", name="uq_app_users_telegram_user_id"))
    op.create_index("ix_app_users_telegram_user_id", "app_users", ["telegram_user_id"])
    op.create_table("items", sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_url", sa.Text(), nullable=False), sa.Column("size", sa.String(64)),
        sa.Column("color", sa.String(128)), sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("customer_note", sa.Text()), sa.Column("status", item_status, nullable=False),
        sa.Column("listed_price", sa.Numeric(14, 2)), sa.Column("listed_currency", sa.String(3)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_user_id"], ["app_users.id"], ondelete="RESTRICT",
                                name="fk_items_customer_user_id_app_users"),
        sa.PrimaryKeyConstraint("id", name="pk_items"))
    op.create_index("ix_items_customer_user_id", "items", ["customer_user_id"])
    op.create_index("ix_items_status", "items", ["status"])

def downgrade():
    op.drop_table("items")
    op.drop_table("app_users")
    item_status.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
