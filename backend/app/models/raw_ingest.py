"""
Raw ingest landing table (Phase 0 Foundation).

Every file entering the platform passes through the 5-stage pipeline:
landed → staged → normalised → reconciled → served (or failed).
The raw payload is kept verbatim (JSON) so any stage can be replayed.
file_hash (sha256) is unique — the same file is never ingested twice.
"""
from datetime import datetime, date
import enum
from sqlalchemy import String, DateTime, Date, ForeignKey, Enum, Integer, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class IngestStage(str, enum.Enum):
    LANDED = "landed"
    STAGED = "staged"
    NORMALISED = "normalised"
    RECONCILED = "reconciled"
    SERVED = "served"
    FAILED = "failed"


class RawIngest(Base):
    __tablename__ = "raw_ingests"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "micros"
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # sha256
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=True)
    stage: Mapped[IngestStage] = mapped_column(Enum(IngestStage), nullable=False, default=IngestStage.LANDED)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    org_unit: Mapped["OrgUnit"] = relationship()
