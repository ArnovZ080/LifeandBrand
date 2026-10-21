"""Feature 1: wastage logging and full stock counts.

Creates waste_events, count_templates, stock_counts and stock_count_lines.
Enum labels are the lowercase member values (matching the models'
values_callable). The movement types WASTE and ADJUSTMENT already exist on
stock_movements, so no change is needed there.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waste_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 4), nullable=False),
        sa.Column(
            "reason",
            sa.Enum("spoilage", "overproduction", "prep_error", "expired",
                    "staff_meal", "customer_return", "other", name="wastereason"),
            nullable=False,
        ),
        sa.Column("reason_note", sa.Text, nullable=True),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("cost_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("logged_by", sa.String(100), nullable=True),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_waste_events_unit_date", "waste_events", ["org_unit_id", "event_date"])

    op.create_table(
        "count_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=True),
        sa.Column("item_ids", sa.JSON, nullable=False),  # ordered list of item ids
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "stock_counts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("count_templates.id"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("count_date", sa.Date, nullable=False),
        sa.Column("status", sa.Enum("open", "submitted", name="stockcountstatus"),
                  nullable=False, server_default="open"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_stock_counts_unit_date", "stock_counts", ["org_unit_id", "count_date"])

    op.create_table(
        "stock_count_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_count_id", sa.Integer, sa.ForeignKey("stock_counts.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("system_qty", sa.Numeric(10, 4), nullable=False),
        sa.Column("counted_qty", sa.Numeric(10, 4), nullable=True),
        sa.Column("variance_qty", sa.Numeric(10, 4), nullable=True),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("variance_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("counted_by", sa.String(100), nullable=True),
        sa.Column("counted_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("stock_count_id", "item_id", name="uq_stock_count_lines_count_item"),
    )


def downgrade() -> None:
    op.drop_table("stock_count_lines")
    op.drop_index("ix_stock_counts_unit_date", "stock_counts")
    op.drop_table("stock_counts")
    op.drop_table("count_templates")
    op.drop_index("ix_waste_events_unit_date", "waste_events")
    op.drop_table("waste_events")
    op.execute("DROP TYPE IF EXISTS stockcountstatus")
    op.execute("DROP TYPE IF EXISTS wastereason")
