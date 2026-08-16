"""
Autonomy Ladder (Phase 0 Foundation).

Each automatable action type sits on a rung 0–5 (0 = observe only,
5 = fully autonomous). Promotion requires `required_clean_runs` consecutive
clean runs, and — above rung 2 — the gating ledger metric must be green.
Every clean run, human edit, veto, reversal, promotion and demotion is
recorded as an AutonomyEvent.
"""
from datetime import datetime
import enum
from sqlalchemy import String, DateTime, ForeignKey, Enum, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class AutonomyEventKind(str, enum.Enum):
    CLEAN_RUN = "clean_run"
    EDIT = "edit"
    VETO = "veto"
    REVERSAL = "reversal"
    PROMOTION = "promotion"
    DEMOTION = "demotion"


class ActionType(Base):
    __tablename__ = "autonomy_action_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_rung: Mapped[int] = mapped_column(Integer, default=0)  # 0–5
    required_clean_runs: Mapped[int] = mapped_column(Integer, default=10)
    clean_run_count: Mapped[int] = mapped_column(Integer, default=0)
    # Ledger metric that must be green for promotion above rung 2
    gating_metric_key: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    events: Mapped[list["AutonomyEvent"]] = relationship(back_populates="action_type")


class AutonomyEvent(Base):
    __tablename__ = "autonomy_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    action_type_id: Mapped[int] = mapped_column(ForeignKey("autonomy_action_types.id"), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    event_kind: Mapped[AutonomyEventKind] = mapped_column(Enum(AutonomyEventKind), nullable=False)
    from_rung: Mapped[int] = mapped_column(Integer, nullable=True)
    to_rung: Mapped[int] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    action_type: Mapped["ActionType"] = relationship(back_populates="events")
    org_unit: Mapped["OrgUnit"] = relationship()
