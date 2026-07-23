"""Phase 0: org structure and auth — rename locations to org_units, add Brand/User tables.

Revision ID: 0001
Revises: (initial)
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create brands table ────────────────────────────────────────────────
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )

    # ── 2. Rename locations → org_units (PostgreSQL auto-updates FK refs) ─────
    op.rename_table("locations", "org_units")

    # ── 3. Add new columns to org_units ──────────────────────────────────────
    op.add_column("org_units", sa.Column(
        "tier",
        sa.Enum("site", "area", "regional", "national", "md", "ceo", name="orgtier"),
        nullable=False,
        server_default="site",
    ))
    op.add_column("org_units", sa.Column("parent_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=True))
    op.add_column("org_units", sa.Column("brand_id", sa.Integer, sa.ForeignKey("brands.id"), nullable=True))
    op.add_column("org_units", sa.Column("pos_site_code", sa.String(50), nullable=True))

    # Make code nullable (was NOT NULL on Location, now optional for non-SITE tiers)
    op.alter_column("org_units", "code", nullable=True)

    # Remove the server_default we added for existing rows
    op.alter_column("org_units", "tier", server_default=None)

    # ── 4. Create users table ─────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "role",
            sa.Enum("site_gm", "area_manager", "regional_manager", "national_ops", "md", "ceo", name="userrole"),
            nullable=False,
        ),
        sa.Column("org_unit_id", sa.Integer, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole")

    op.drop_column("org_units", "pos_site_code")
    op.drop_column("org_units", "brand_id")
    op.drop_column("org_units", "parent_id")
    op.drop_column("org_units", "tier")
    op.execute("DROP TYPE IF EXISTS orgtier")

    op.rename_table("org_units", "locations")
    op.drop_table("brands")
