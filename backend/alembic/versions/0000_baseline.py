"""Baseline: base tables that predate the Alembic history.

Creates the tables, enum types, constraints and foreign keys that existed before
migration 0001 was written. Every existing deployment was built from
Base.metadata.create_all, so this revision is a no-op for them when they are
stamped at a later revision. On an empty database it recreates the starting
point that 0001 expects.

Enum labels are the Python member names (the default Enum storage).

Revision ID: 0000
Revises: (none)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None


# create_type=False: the enum types are created once, explicitly, in upgrade().
alert_status = postgresql.ENUM("SENT", "FAILED", "SUPPRESSED", name="alertstatus", create_type=False)
batch_status = postgresql.ENUM("ACTIVE", "EXPIRING_SOON", "EXPIRED", "DEPLETED", name="batchstatus", create_type=False)
checklist_frequency = postgresql.ENUM("DAILY", "WEEKLY", "MONTHLY", "ADHOC", name="checklistfrequency", create_type=False)
delivery_status = postgresql.ENUM("PENDING", "VERIFIED", "DISCREPANCY", "ACCEPTED", name="deliverystatus", create_type=False)
department = postgresql.ENUM("BAR", "KITCHEN", "FLOOR", "GENERAL", name="department", create_type=False)
invoice_status = postgresql.ENUM("DRAFT", "MATCHED", "APPROVED", "POSTED", "DISPUTED", name="invoicestatus", create_type=False)
movement_type = postgresql.ENUM(
    "DELIVERY", "SALE", "WASTE", "TRANSFER_IN", "TRANSFER_OUT", "ADJUSTMENT", "OPENING",
    name="movementtype", create_type=False,
)
notification_channel = postgresql.ENUM("EMAIL", "TEAMS", "WHATSAPP", name="notificationchannel", create_type=False)
po_status = postgresql.ENUM("DRAFT", "SENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED", name="postatus", create_type=False)
spot_check_status = postgresql.ENUM("PENDING", "PARTIAL", "COMPLETE", "MISSED", name="spotcheckstatus", create_type=False)

ENUM_TYPES = [
    alert_status, batch_status, checklist_frequency, delivery_status, department,
    invoice_status, movement_type, notification_channel, po_status, spot_check_status,
]

# Drop order: dependants before the tables they reference.
BASE_TABLES = [
    "spot_check_batch_counts",
    "spot_check_items",
    "spot_check_sessions",
    "expiry_alerts",
    "am_checklist_entries",
    "am_checklist_tasks",
    "one_on_one_meetings",
    "ops_visit_reports",
    "sale_lines",
    "sales",
    "stock_movements",
    "invoice_lines",
    "invoices",
    "item_batches",
    "delivery_lines",
    "deliveries",
    "purchase_order_lines",
    "purchase_orders",
    "recipe_lines",
    "menu_items",
    "location_contacts",
    "locations",
    "supplier_items",
    "items",
    "units_of_measure",
    "suppliers",
]


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "units_of_measure",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("abbreviation", sa.String(10), nullable=False, unique=True),
    )

    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("contact_name", sa.String(100), nullable=True),
        sa.Column("contact_email", sa.String(200), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("payment_terms_days", sa.Integer, nullable=False),
        sa.Column("sage_supplier_id", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column(
            "department",
            department,
            nullable=False,
        ),
        sa.Column("unit_of_measure_id", sa.Integer, sa.ForeignKey("units_of_measure.id"), nullable=False),
        sa.Column("pack_size", sa.Numeric(10, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_perishable", sa.Boolean, nullable=False),
        sa.Column("default_shelf_life_days", sa.Integer, nullable=True),
        sa.Column("reorder_level", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "supplier_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("supplier_sku", sa.String(100), nullable=True),
        sa.Column("supplier_item_name", sa.String(200), nullable=True),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=False),
        sa.Column("pack_size", sa.Numeric(10, 4), nullable=False),
        sa.Column("is_preferred", sa.Boolean, nullable=False),
        sa.Column("effective_date", sa.DateTime, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "location_contacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("whatsapp_number", sa.String(30), nullable=True),
        sa.Column("teams_webhook_url", sa.String(500), nullable=True),
        sa.Column("active_channels", sa.String(100), nullable=False),
        sa.Column("departments_subscribed", sa.String(200), nullable=False),
        sa.Column("quiet_hours_start", sa.Integer, nullable=False),
        sa.Column("quiet_hours_end", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("micros_item_id", sa.String(100), nullable=True, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("sale_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "recipe_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("menu_item_id", sa.Integer, sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("quantity_used", sa.Numeric(10, 6), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("po_number", sa.String(50), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column(
            "status",
            po_status,
            nullable=False,
        ),
        sa.Column("order_date", sa.Date, nullable=False),
        sa.Column("expected_delivery_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("purchase_order_id", sa.Integer, sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("supplier_item_id", sa.Integer, sa.ForeignKey("supplier_items.id"), nullable=True),
        sa.Column("quantity_ordered", sa.Numeric(10, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=False),
        sa.Column("quantity_received", sa.Numeric(10, 4), nullable=False),
    )

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("grn_number", sa.String(50), nullable=False, unique=True),
        sa.Column("purchase_order_id", sa.Integer, sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("delivery_date", sa.Date, nullable=False),
        sa.Column("supplier_delivery_note", sa.String(100), nullable=True),
        sa.Column(
            "status",
            delivery_status,
            nullable=False,
        ),
        sa.Column("received_by", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "delivery_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("delivery_id", sa.Integer, sa.ForeignKey("deliveries.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("po_line_id", sa.Integer, sa.ForeignKey("purchase_order_lines.id"), nullable=True),
        sa.Column("quantity_delivered", sa.Numeric(10, 4), nullable=False),
        sa.Column("quantity_accepted", sa.Numeric(10, 4), nullable=True),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("has_discrepancy", sa.Boolean, nullable=False),
        sa.Column("discrepancy_notes", sa.Text, nullable=True),
        sa.Column("best_before_date", sa.Date, nullable=True),
        sa.Column("batch_reference", sa.String(100), nullable=True),
    )

    op.create_table(
        "item_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("delivery_line_id", sa.Integer, sa.ForeignKey("delivery_lines.id"), nullable=True),
        sa.Column("batch_reference", sa.String(100), nullable=True),
        sa.Column("received_date", sa.Date, nullable=False),
        sa.Column("best_before_date", sa.Date, nullable=True),
        sa.Column("shelf_life_days", sa.Integer, nullable=True),
        sa.Column("quantity_received", sa.Numeric(10, 4), nullable=False),
        sa.Column("quantity_remaining", sa.Numeric(10, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "status",
            batch_status,
            nullable=False,
        ),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("delivery_id", sa.Integer, sa.ForeignKey("deliveries.id"), nullable=True),
        sa.Column("invoice_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("subtotal", sa.Numeric(12, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column(
            "status",
            invoice_status,
            nullable=False,
        ),
        sa.Column("sage_invoice_id", sa.String(100), nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=True),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 4), nullable=False),
    )

    op.create_table(
        "expiry_alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("item_batches.id"), nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("location_contacts.id"), nullable=False),
        sa.Column("alert_level", sa.Integer, nullable=False),
        sa.Column(
            "channel",
            notification_channel,
            nullable=False,
        ),
        sa.Column(
            "status",
            alert_status,
            nullable=False,
        ),
        sa.Column("message_preview", sa.Text, nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("movement_type", movement_type, nullable=False),
        sa.Column("quantity", sa.Numeric(10, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("reference_id", sa.Integer, nullable=True),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "sales",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("sale_date", sa.Date, nullable=False),
        sa.Column("micros_batch_id", sa.String(100), nullable=True),
        sa.Column("total_revenue", sa.Numeric(12, 4), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "sale_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sale_id", sa.Integer, sa.ForeignKey("sales.id"), nullable=False),
        sa.Column("menu_item_id", sa.Integer, sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("quantity_sold", sa.Numeric(10, 4), nullable=False),
        sa.Column("revenue", sa.Numeric(12, 4), nullable=True),
    )

    op.create_table(
        "spot_check_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column(
            "department",
            department,
            nullable=False,
        ),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("session_slot", sa.Integer, nullable=False),
        sa.Column(
            "status",
            spot_check_status,
            nullable=False,
        ),
        sa.Column("assigned_to", sa.String(200), nullable=True),
        sa.Column("notified_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "spot_check_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("spot_check_sessions.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("selection_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("velocity_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("value_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("variance_history_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("days_since_last_check", sa.Integer, nullable=True),
        sa.Column("is_overdue", sa.Boolean, nullable=False),
        sa.Column("is_perishable", sa.Boolean, nullable=False),
        sa.Column("theoretical_quantity", sa.Numeric(10, 4), nullable=True),
        sa.Column("actual_quantity", sa.Numeric(10, 4), nullable=True),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("counted_by", sa.String(100), nullable=True),
        sa.Column("counted_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("variance_quantity", sa.Numeric(10, 4), nullable=True),
        sa.Column("variance_value", sa.Numeric(12, 4), nullable=True),
        sa.Column("variance_pct", sa.Numeric(8, 4), nullable=True),
    )

    op.create_table(
        "spot_check_batch_counts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("spot_check_item_id", sa.Integer, sa.ForeignKey("spot_check_items.id"), nullable=False),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("item_batches.id"), nullable=False),
        sa.Column("received_date", sa.Date, nullable=True),
        sa.Column("best_before_date", sa.Date, nullable=True),
        sa.Column("batch_reference", sa.String(100), nullable=True),
        sa.Column("expected_quantity", sa.Numeric(10, 4), nullable=True),
        sa.Column("actual_quantity", sa.Numeric(10, 4), nullable=True),
        sa.Column("counted_by", sa.String(100), nullable=True),
        sa.Column("counted_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("variance_quantity", sa.Numeric(10, 4), nullable=True),
        sa.Column("days_until_expiry", sa.Integer, nullable=True),
    )

    op.create_table(
        "am_checklist_tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "frequency",
            checklist_frequency,
            nullable=False,
        ),
        sa.Column("order_num", sa.Integer, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
    )

    op.create_table(
        "am_checklist_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("am_checklist_tasks.id"), nullable=False),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("period_date", sa.Date, nullable=False),
        sa.Column("completed", sa.Boolean, nullable=False),
        sa.Column("completed_by", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("validated", sa.Boolean, nullable=False),
        sa.Column("validated_by", sa.String(100), nullable=True),
        sa.Column("validated_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "ops_visit_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("visit_date", sa.Date, nullable=False),
        sa.Column("visit_time", sa.String(20), nullable=True),
        sa.Column("visit_done_by", sa.String(100), nullable=False),
        sa.Column("manager_on_duty", sa.String(100), nullable=True),
        sa.Column("gm_of_store", sa.String(100), nullable=True),
        sa.Column("store_trading_hours", sa.String(50), nullable=True),
        sa.Column("foh", sa.JSON, nullable=False),
        sa.Column("boh", sa.JSON, nullable=False),
        sa.Column("admin", sa.JSON, nullable=False),
        sa.Column("general_property", sa.JSON, nullable=False),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("complaints_resolution", sa.Text, nullable=True),
        sa.Column("hr_support", sa.Text, nullable=True),
        sa.Column("mod_signature", sa.String(100), nullable=True),
        sa.Column("am_signature", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "one_on_one_meetings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("team_member_name", sa.String(150), nullable=False),
        sa.Column("area_manager_name", sa.String(150), nullable=False),
        sa.Column("meeting_date", sa.Date, nullable=False),
        sa.Column("q1_experience", sa.Text, nullable=True),
        sa.Column("q2_improvements", sa.Text, nullable=True),
        sa.Column("q3_concerns", sa.Text, nullable=True),
        sa.Column("q4_growth_next_year", sa.Text, nullable=True),
        sa.Column("q5_long_term_goals", sa.Text, nullable=True),
        sa.Column("q6_mobility", sa.Text, nullable=True),
        sa.Column("q7_workplace_issues", sa.Text, nullable=True),
        sa.Column("q8_training", sa.Text, nullable=True),
        sa.Column("q9_additional_notes", sa.Text, nullable=True),
        sa.Column("team_member_signature", sa.String(150), nullable=True),
        sa.Column("am_signature", sa.String(150), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    for table in BASE_TABLES:
        op.drop_table(table)
    for enum_type in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {enum_type.name}")
