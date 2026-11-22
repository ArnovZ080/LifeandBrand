"""Stock counts: blind-count flag and the site list.

Adds stock_counts.blind (default false). Blind counts hide system quantities
and variances from the API until the count is submitted. No enum types change.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_counts",
        sa.Column("blind", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("stock_counts", "blind")
