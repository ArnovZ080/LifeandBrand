"""Shopping list: per-venue par levels.

Creates par_levels with the unique constraint (one par per site and item) and an
index on org_unit_id. No enum types are added.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "par_levels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("par_qty", sa.Numeric(10, 4), nullable=False),
        sa.Column("reorder_point", sa.Numeric(10, 4), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_unit_id", "item_id", name="uq_par_levels_unit_item"),
    )
    op.create_index("ix_par_levels_org_unit", "par_levels", ["org_unit_id"])


def downgrade() -> None:
    op.drop_index("ix_par_levels_org_unit", table_name="par_levels")
    op.drop_table("par_levels")
