"""Feature 4: sales forecast runs and lines.

Creates forecast_runs and forecast_lines with their indexes and the unique
constraint that allows one line per run, business date and menu item. No enum
types are added.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("horizon_days", sa.Integer, nullable=False),
        sa.Column("history_days", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(100), nullable=True),
    )
    op.create_index("ix_forecast_runs_unit_date", "forecast_runs", ["org_unit_id", "run_date"])

    op.create_table(
        "forecast_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("forecast_run_id", sa.Integer, sa.ForeignKey("forecast_runs.id"), nullable=False),
        sa.Column("business_date", sa.Date, nullable=False),
        sa.Column("menu_item_id", sa.Integer, sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("baseline_qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("adjusted_qty", sa.Numeric(12, 3), nullable=True),
        sa.Column("adjusted_by", sa.String(100), nullable=True),
        sa.Column("adjustment_note", sa.Text, nullable=True),
        sa.UniqueConstraint("forecast_run_id", "business_date", "menu_item_id",
                            name="uq_forecast_lines_run_date_item"),
    )


def downgrade() -> None:
    op.drop_table("forecast_lines")
    op.drop_index("ix_forecast_runs_unit_date", table_name="forecast_runs")
    op.drop_table("forecast_runs")
