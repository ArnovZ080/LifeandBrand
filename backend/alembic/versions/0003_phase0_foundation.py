"""Phase 0 Foundation: tenants, accuracy ledger, autonomy ladder, vendor price
catalogue, budgets, raw ingest pipeline; tenant_id on org_units; recipe validity dates.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Tenants ───────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.add_column("org_units", sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=True))

    # ── Accuracy Ledger ───────────────────────────────────────────────────────
    op.create_table(
        "ledger_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("tolerance_pct", sa.Float, nullable=False),
        sa.Column("required_green_periods", sa.Integer, nullable=False, server_default="14"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("metric_id", sa.Integer, sa.ForeignKey("ledger_metrics.id"), nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("period_date", sa.Date, nullable=False),
        sa.Column("computed_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("ground_truth_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("within_tolerance", sa.Boolean, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ledger_entries_metric_unit_period",
        "ledger_entries",
        ["metric_id", "org_unit_id", "period_date"],
    )

    # ── Autonomy Ladder ───────────────────────────────────────────────────────
    op.create_table(
        "autonomy_action_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("current_rung", sa.Integer, nullable=False, server_default="0"),
        sa.Column("required_clean_runs", sa.Integer, nullable=False, server_default="10"),
        sa.Column("clean_run_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("gating_metric_key", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "autonomy_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("action_type_id", sa.Integer, sa.ForeignKey("autonomy_action_types.id"), nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=True),
        sa.Column(
            "event_kind",
            sa.Enum("clean_run", "edit", "veto", "reversal", "promotion", "demotion",
                    name="autonomyeventkind"),
            nullable=False,
        ),
        sa.Column("from_rung", sa.Integer, nullable=True),
        sa.Column("to_rung", sa.Integer, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── Vendor Price Catalogue ────────────────────────────────────────────────
    op.create_table(
        "vendor_price_catalogue",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=True),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vpc_item_supplier", "vendor_price_catalogue", ["item_id", "supplier_id"])

    # ── Budgets ───────────────────────────────────────────────────────────────
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("metric_key", sa.String(100), nullable=False),
        sa.Column("value", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_unit_id", "year", "month", "metric_key",
                            name="uq_budget_unit_period_metric"),
    )

    # ── Raw ingest pipeline ───────────────────────────────────────────────────
    op.create_table(
        "raw_ingests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("file_name", sa.String(300), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=True),
        sa.Column("business_date", sa.Date, nullable=True),
        sa.Column(
            "stage",
            sa.Enum("landed", "staged", "normalised", "reconciled", "served", "failed",
                    name="ingeststage"),
            nullable=False,
            server_default="landed",
        ),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_raw_ingests_stage", "raw_ingests", ["stage"])

    # ── Recipe validity dates ─────────────────────────────────────────────────
    op.add_column("recipe_lines", sa.Column("valid_from", sa.Date, nullable=True))
    op.add_column("recipe_lines", sa.Column("valid_to", sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column("recipe_lines", "valid_to")
    op.drop_column("recipe_lines", "valid_from")
    op.drop_index("ix_raw_ingests_stage", "raw_ingests")
    op.drop_table("raw_ingests")
    op.execute("DROP TYPE IF EXISTS ingeststage")
    op.drop_table("budgets")
    op.drop_index("ix_vpc_item_supplier", "vendor_price_catalogue")
    op.drop_table("vendor_price_catalogue")
    op.drop_table("autonomy_events")
    op.execute("DROP TYPE IF EXISTS autonomyeventkind")
    op.drop_table("autonomy_action_types")
    op.drop_index("ix_ledger_entries_metric_unit_period", "ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_table("ledger_metrics")
    op.drop_column("org_units", "tenant_id")
    op.drop_table("tenants")
