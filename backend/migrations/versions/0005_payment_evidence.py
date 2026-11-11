"""payment evidence for individual items"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_payment_evidence"
down_revision = "0004_finance"
branch_labels = None
depends_on = None
UUID = postgresql.UUID(as_uuid=True)


def upgrade():
    op.create_table(
        "payment_evidence",
        sa.Column("item_id", UUID, nullable=False),
        sa.Column("submitted_by_user_id", UUID, nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("stored_filename", sa.String(255)),
        sa.Column("telegram_file_id", sa.Text()),
        sa.Column("telegram_file_unique_id", sa.String(255)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "note IS NOT NULL OR stored_filename IS NOT NULL",
            name="ck_payment_evidence_note_or_file_required",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"], ["app_users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index("ix_payment_evidence_item_id", "payment_evidence", ["item_id"])
    op.create_index(
        "ix_payment_evidence_submitted_by_user_id",
        "payment_evidence",
        ["submitted_by_user_id"],
    )


def downgrade():
    op.drop_table("payment_evidence")
