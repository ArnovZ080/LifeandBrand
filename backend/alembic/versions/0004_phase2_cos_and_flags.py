"""Phase 2 COS engine: cos_flags + cos_dismissals tables and CosCause enum.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cos_flags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),  # "YYYY-MM"
        sa.Column("actual_qty", sa.Numeric(12, 3), nullable=True),
        sa.Column("theoretical_qty", sa.Numeric(12, 3), nullable=True),
        sa.Column("variance_qty", sa.Numeric(12, 3), nullable=True),
        sa.Column("variance_value", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "cause",
            sa.Enum("counting_swap", "timing", "spillage", "process_failure",
                    "immediate", "known_baseline", name="coscause"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_cos_flags_unit_period", "cos_flags", ["org_unit_id", "period"])

    op.create_table(
        "cos_dismissals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flag_id", sa.Integer, sa.ForeignKey("cos_flags.id"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("dismissed_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("cos_dismissals")
    op.drop_index("ix_cos_flags_unit_period", "cos_flags")
    op.drop_table("cos_flags")
    op.execute("DROP TYPE IF EXISTS coscause")
