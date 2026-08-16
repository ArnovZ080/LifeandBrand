"""
Tenant — top-level multi-tenancy anchor (Phase 0 Foundation).

A tenant owns brands and org units. Phase 0 seeds a single tenant
("Life & Brand Portfolio"); the column is nullable on org_units so existing
rows keep working until backfilled.
"""
from datetime import datetime
from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
