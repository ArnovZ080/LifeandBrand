"""Feature 2: requisitions and multi-level approvals.

Creates requisitions, requisition_lines, approval_rules, approval_requests and
approval_decisions, plus their Postgres enum types. Enum labels are the Python
member NAMES (the models use the default Enum(...) storage, so no
values_callable). Migration 0005 is unchanged.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# create_type=False: the enum types are created once, explicitly, in upgrade().
requisition_status = postgresql.ENUM(
    "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CONVERTED", "CANCELLED",
    name="requisitionstatus", create_type=False,
)
approval_subject = postgresql.ENUM(
    "REQUISITION", "PURCHASE_ORDER", name="approvalsubject", create_type=False,
)
approval_status = postgresql.ENUM(
    "PENDING", "APPROVED", "REJECTED", name="approvalstatus", create_type=False,
)
decision_outcome = postgresql.ENUM(
    "APPROVED", "REJECTED", name="decisionoutcome", create_type=False,
)

ENUM_TYPES = ["requisitionstatus", "approvalsubject", "approvalstatus", "decisionoutcome"]


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (requisition_status, approval_subject, approval_status, decision_outcome):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "requisitions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("requisition_number", sa.String(50), nullable=False, unique=True),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("status", requisition_status, nullable=False, server_default="DRAFT"),
        sa.Column("needed_by", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("total_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "requisition_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("requisition_id", sa.Integer, sa.ForeignKey("requisitions.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("requisition_id", "item_id", name="uq_requisition_lines_req_item"),
    )

    op.create_table(
        "approval_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject", approval_subject, nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=True),
        sa.Column("min_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("max_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("levels", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject", approval_subject, nullable=False),
        sa.Column("subject_id", sa.Integer, nullable=False),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("approval_rules.id"), nullable=True),
        sa.Column("levels", sa.JSON, nullable=False),
        sa.Column("current_level", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", approval_status, nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("subject", "subject_id", name="uq_approval_requests_subject"),
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("approval_request_id", sa.Integer, sa.ForeignKey("approval_requests.id"), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("approver_name", sa.String(120), nullable=False),
        sa.Column("approver_role", sa.String(40), nullable=False),
        sa.Column("decision", decision_outcome, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("approval_decisions")
    op.drop_table("approval_requests")
    op.drop_table("approval_rules")
    op.drop_table("requisition_lines")
    op.drop_table("requisitions")
    for name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {name}")
