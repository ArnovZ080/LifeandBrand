"""Phase 1: operational alerts layer — OpsAlertType, ThresholdConfig, OpsAlert, EscalationEvent.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Alert types catalogue ─────────────────────────────────────────────────
    op.create_table(
        "ops_alert_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("source_module", sa.String(50), nullable=False),
        sa.Column("base_severity_weight", sa.Numeric(5, 2), nullable=False, server_default="1.0"),
    )

    # ── Threshold configs ─────────────────────────────────────────────────────
    op.create_table(
        "threshold_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kpi_type", sa.String(50), nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("value", sa.Numeric(10, 4), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("lower_is_better", "higher_is_better", "target_band", name="thresholddirection"),
            nullable=False,
        ),
        sa.Column("set_by_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("set_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("learned_adjustment", sa.Numeric(6, 4), nullable=True),
    )
    op.create_index("ix_threshold_kpi_unit", "threshold_configs", ["kpi_type", "org_unit_id"], unique=True)

    # ── Generalised alerts ────────────────────────────────────────────────────
    op.create_table(
        "ops_alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("alert_type_id", sa.Integer, sa.ForeignKey("ops_alert_types.id"), nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="opsseverity"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum("open", "acknowledged", "escalated", "resolved", name="opsalertstate"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("visible_tiers", sa.String(200), nullable=False, server_default="site"),
        sa.Column("source_event_ref", sa.String(200), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime, nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_ops_alerts_source_ref", "ops_alerts", ["source_event_ref"])
    op.create_index("ix_ops_alerts_state", "ops_alerts", ["state"])

    # ── Escalation event log ──────────────────────────────────────────────────
    op.create_table(
        "escalation_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("alert_id", sa.Integer, sa.ForeignKey("ops_alerts.id"), nullable=False),
        sa.Column(
            "action",
            sa.Enum("acknowledged", "escalated_manual", "escalated_auto", "resolved",
                    "dismissed_not_useful", name="escalationaction"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── Seed the freshness_expiry alert type ──────────────────────────────────
    op.execute(
        "INSERT INTO ops_alert_types (key, name, source_module, base_severity_weight) "
        "VALUES ('freshness_expiry', 'Freshness / Expiry Warning', 'batches', 1.5)"
    )
    op.execute(
        "INSERT INTO ops_alert_types (key, name, source_module, base_severity_weight) "
        "VALUES ('stock_below_par', 'Stock Below Par Level', 'stock', 1.0)"
    )
    op.execute(
        "INSERT INTO ops_alert_types (key, name, source_module, base_severity_weight) "
        "VALUES ('checklist_overdue', 'AM Checklist Task Overdue', 'am_checklist', 0.8)"
    )
    op.execute(
        "INSERT INTO ops_alert_types (key, name, source_module, base_severity_weight) "
        "VALUES ('cos_variance', 'Cost of Sale Variance', 'spot_checks', 1.2)"
    )


def downgrade() -> None:
    op.drop_table("escalation_events")
    op.execute("DROP TYPE IF EXISTS escalationaction")
    op.drop_index("ix_ops_alerts_state", "ops_alerts")
    op.drop_index("ix_ops_alerts_source_ref", "ops_alerts")
    op.drop_table("ops_alerts")
    op.execute("DROP TYPE IF EXISTS opsalertstate")
    op.execute("DROP TYPE IF EXISTS opsseverity")
    op.drop_index("ix_threshold_kpi_unit", "threshold_configs")
    op.drop_table("threshold_configs")
    op.execute("DROP TYPE IF EXISTS thresholddirection")
    op.drop_table("ops_alert_types")
