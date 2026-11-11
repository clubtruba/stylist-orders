"""customers, commerce, deliveries and shipments"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_commerce"
down_revision = "0002_operational_guards"
branch_labels = None
depends_on = None
UUID = postgresql.UUID(as_uuid=True)
collection_status = postgresql.ENUM("COLLECTING", "READY_TO_SHIP", "SHIPMENT_REQUESTED", name="collection_status", create_type=False)
allocation_method = postgresql.ENUM("EQUAL", "PROPORTIONAL_BY_VALUE", "MANUAL", "UNALLOCATED", name="allocation_method", create_type=False)
shipment_status = postgresql.ENUM("PREPARING", "SHIPPED", "DELIVERED", "CANCELLED", name="shipment_status", create_type=False)


def identity_and_timestamps():
    return [sa.Column("id", UUID, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    for value in (collection_status, allocation_method, shipment_status):
        value.create(op.get_bind(), checkfirst=True)
    op.create_table("customers",
        sa.Column("app_user_id", UUID), sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(50)), sa.Column("internal_note", sa.Text()),
        sa.Column("collection_status", collection_status, nullable=False),
        sa.Column("financial_details_visible", sa.Boolean(), nullable=False), *identity_and_timestamps(),
        sa.ForeignKeyConstraint(["app_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_customers"), sa.UniqueConstraint("app_user_id"))
    op.create_index("ix_customers_display_name", "customers", ["display_name"])
    op.execute("INSERT INTO customers (id, app_user_id, display_name, collection_status, financial_details_visible) SELECT gen_random_uuid(), id, first_name, 'COLLECTING', false FROM app_users")
    op.add_column("items", sa.Column("customer_id", UUID, nullable=True))
    op.execute("UPDATE items SET customer_id = customers.id FROM customers WHERE customers.app_user_id = items.customer_user_id")
    op.alter_column("items", "customer_id", nullable=False)
    op.create_foreign_key("fk_items_customer_id_customers", "items", "customers", ["customer_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_items_customer_id", "items", ["customer_id"])
    op.drop_constraint("fk_items_customer_user_id_app_users", "items", type_="foreignkey")
    op.drop_index("ix_items_customer_user_id", table_name="items")
    op.drop_column("items", "customer_user_id")
    op.create_table("customer_addresses",
        sa.Column("customer_id", UUID, nullable=False), sa.Column("label", sa.String(100), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False), sa.Column("phone", sa.String(50)),
        sa.Column("country_code", sa.String(2), nullable=False), sa.Column("postal_code", sa.String(32), nullable=False),
        sa.Column("region", sa.String(200)), sa.Column("city", sa.String(200), nullable=False),
        sa.Column("address_line1", sa.String(300), nullable=False), sa.Column("address_line2", sa.String(300)),
        sa.Column("is_default", sa.Boolean(), nullable=False), *identity_and_timestamps(),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])
    op.create_index("uq_customer_addresses_one_default", "customer_addresses", ["customer_id"], unique=True, postgresql_where=sa.text("is_default"))
    op.create_table("merchants", sa.Column("name", sa.String(200), nullable=False), sa.Column("domain", sa.String(255)), *identity_and_timestamps(), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("name"), sa.UniqueConstraint("domain"))
    op.create_table("merchant_purchases",
        sa.Column("merchant_id", UUID, nullable=False), sa.Column("external_order_number", sa.String(200)),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("merchant_shipping_cost", sa.Numeric(14,2), nullable=False),
        sa.Column("merchant_discount", sa.Numeric(14,2), nullable=False), sa.Column("other_cost", sa.Numeric(14,2), nullable=False),
        sa.Column("allocation_method", allocation_method, nullable=False), sa.Column("purchased_at", sa.DateTime(timezone=True)), *identity_and_timestamps(),
        sa.CheckConstraint("char_length(currency) = 3", name="ck_merchant_purchases_currency_iso_length"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"))
    op.create_table("merchant_purchase_items", sa.Column("purchase_id", UUID, nullable=False), sa.Column("item_id", UUID, nullable=False), sa.Column("actual_purchase_price", sa.Numeric(14,2), nullable=False), sa.Column("allocated_shipping", sa.Numeric(14,2), nullable=False), sa.Column("allocated_discount", sa.Numeric(14,2), nullable=False), sa.Column("id", UUID, nullable=False), sa.ForeignKeyConstraint(["purchase_id"],["merchant_purchases.id"],ondelete="CASCADE"), sa.ForeignKeyConstraint(["item_id"],["items.id"],ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("item_id"))
    op.create_table("merchant_deliveries", sa.Column("purchase_id", UUID, nullable=False), sa.Column("carrier", sa.String(100)), sa.Column("tracking_number", sa.String(200)), sa.Column("expected_at", sa.DateTime(timezone=True)), sa.Column("received_at", sa.DateTime(timezone=True)), *identity_and_timestamps(), sa.ForeignKeyConstraint(["purchase_id"],["merchant_purchases.id"],ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_table("merchant_delivery_items", sa.Column("delivery_id", UUID, nullable=False), sa.Column("item_id", UUID, nullable=False), sa.Column("id", UUID, nullable=False), sa.ForeignKeyConstraint(["delivery_id"],["merchant_deliveries.id"],ondelete="CASCADE"), sa.ForeignKeyConstraint(["item_id"],["items.id"],ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("delivery_id","item_id"))
    op.create_table("customer_shipments",
        sa.Column("customer_id", UUID, nullable=False), sa.Column("status", shipment_status, nullable=False), sa.Column("carrier", sa.String(100)), sa.Column("tracking_number", sa.String(200)), sa.Column("currency", sa.String(3), nullable=False),
        *[sa.Column(name, sa.Numeric(14,2), nullable=False) for name in ("shipping_cost","packaging_cost","insurance_cost","customs_fee","other_fee")],
        sa.Column("address_recipient_name", sa.String(200), nullable=False), sa.Column("address_phone", sa.String(50)), sa.Column("address_country_code", sa.String(2), nullable=False), sa.Column("address_postal_code", sa.String(32), nullable=False), sa.Column("address_region", sa.String(200)), sa.Column("address_city", sa.String(200), nullable=False), sa.Column("address_line1", sa.String(300), nullable=False), sa.Column("address_line2", sa.String(300)), sa.Column("shipped_at", sa.DateTime(timezone=True)), sa.Column("delivered_at", sa.DateTime(timezone=True)), *identity_and_timestamps(),
        sa.ForeignKeyConstraint(["customer_id"],["customers.id"],ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"))
    op.create_table("shipment_items", sa.Column("shipment_id", UUID, nullable=False), sa.Column("item_id", UUID, nullable=False), sa.Column("id", UUID, nullable=False), sa.ForeignKeyConstraint(["shipment_id"],["customer_shipments.id"],ondelete="CASCADE"), sa.ForeignKeyConstraint(["item_id"],["items.id"],ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("item_id"))
    for table, column in (("merchant_purchases","merchant_id"),("merchant_purchase_items","purchase_id"),("merchant_deliveries","purchase_id"),("merchant_delivery_items","delivery_id"),("merchant_delivery_items","item_id"),("customer_shipments","customer_id"),("customer_shipments","status"),("shipment_items","shipment_id")):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.add_column("items", sa.Column("customer_user_id", UUID, nullable=True))
    op.execute("UPDATE items SET customer_user_id = customers.app_user_id FROM customers WHERE customers.id = items.customer_id")
    op.create_foreign_key("fk_items_customer_user_id_app_users", "items", "app_users", ["customer_user_id"], ["id"], ondelete="RESTRICT")
    for table in ("shipment_items","customer_shipments","merchant_delivery_items","merchant_deliveries","merchant_purchase_items","merchant_purchases","merchants","customer_addresses"):
        op.drop_table(table)
    op.drop_column("items", "customer_id")
    op.drop_table("customers")
    for value in (shipment_status, allocation_method, collection_status):
        value.drop(op.get_bind(), checkfirst=True)
