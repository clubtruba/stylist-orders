"""read-only staff role"""

from alembic import op

revision = "0006_viewer_role"
down_revision = "0005_payment_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'VIEWER'")


def downgrade():
    # PostgreSQL enum values cannot be removed safely while rows may use them.
    pass
