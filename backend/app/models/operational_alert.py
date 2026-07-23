"""
Generalised alerting layer — sits alongside the existing ExpiryAlert system
(which remains in alert.py and continues to function unchanged).

Phase 1 shadow-mode: alert_engine.run_alert_check() will also write OpsAlert
rows alongside ExpiryAlert rows so both systems run in parallel during validation.
"""
from datetime import datetime
import enum
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class OpsSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OpsAlertState(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class ThresholdDirection(str, enum.Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"
    TARGET_BAND = "target_band"


class EscalationAction(str, enum.Enum):
    ACKNOWLEDGED = "acknowledged"
    ESCALATED_MANUAL = "escalated_manual"
    ESCALATED_AUTO = "escalated_auto"
    RESOLVED = "resolved"
    DISMISSED_NOT_USEFUL = "dismissed_not_useful"


class OpsAlertType(Base):
    __tablename__ = "ops_alert_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    source_module: Mapped[str] = mapped_column(String(50), nullable=False)
    base_severity_weight: Mapped[float] = mapped_column(Numeric(5, 2), default=1.0)


class ThresholdConfig(Base):
    __tablename__ = "threshold_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kpi_type: Mapped[str] = mapped_column(String(50), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    direction: Mapped[ThresholdDirection] = mapped_column(Enum(ThresholdDirection), nullable=False)
    set_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    set_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    learned_adjustment: Mapped[float] = mapped_column(Numeric(6, 4), nullable=True)

    org_unit: Mapped["OrgUnit"] = relationship()
    set_by: Mapped["User"] = relationship()


class OpsAlert(Base):
    __tablename__ = "ops_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_type_id: Mapped[int] = mapped_column(ForeignKey("ops_alert_types.id"), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    severity: Mapped[OpsSeverity] = mapped_column(Enum(OpsSeverity), nullable=False)
    state: Mapped[OpsAlertState] = mapped_column(Enum(OpsAlertState), default=OpsAlertState.OPEN)
    # Comma-separated OrgTier values — widens on auto-escalation
    visible_tiers: Mapped[str] = mapped_column(String(200), nullable=False, default="site")
    # e.g. "expiry_alert:1234" — links back to source system record
    source_event_ref: Mapped[str] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    alert_type: Mapped["OpsAlertType"] = relationship()
    org_unit: Mapped["OrgUnit"] = relationship()
    events: Mapped[list["EscalationEvent"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class EscalationEvent(Base):
    __tablename__ = "escalation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("ops_alerts.id"), nullable=False)
    action: Mapped[EscalationAction] = mapped_column(Enum(EscalationAction), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)  # null = auto
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    alert: Mapped["OpsAlert"] = relationship(back_populates="events")
    actor: Mapped["User"] = relationship()
