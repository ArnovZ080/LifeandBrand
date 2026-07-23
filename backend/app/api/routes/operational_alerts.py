from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.user import User
from app.models.operational_alert import (
    OpsAlert, OpsAlertState, OpsAlertType, EscalationEvent, EscalationAction,
    ThresholdConfig, ThresholdDirection,
)
from app.auth.dependencies import get_current_user, get_accessible_org_unit_ids
from app.services.escalation_engine import check_escalations
from app.services.threshold_resolver import set_threshold, get_effective_threshold, ThresholdConflict

router = APIRouter(prefix="/ops-alerts", tags=["operational-alerts"])


class AlertOut(BaseModel):
    id: int
    alert_type_key: str
    alert_type_name: str
    org_unit_id: int
    org_unit_name: str
    severity: str
    state: str
    visible_tiers: str
    source_event_ref: str | None
    title: str
    detail: str | None
    created_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None

    class Config:
        from_attributes = True


class ThresholdIn(BaseModel):
    kpi_type: str
    org_unit_id: int
    value: float
    direction: ThresholdDirection


class ThresholdOut(BaseModel):
    id: int
    kpi_type: str
    org_unit_id: int
    value: float
    direction: str
    set_at: datetime
    learned_adjustment: float | None

    class Config:
        from_attributes = True


def _alert_out(a: OpsAlert) -> AlertOut:
    return AlertOut(
        id=a.id,
        alert_type_key=a.alert_type.key,
        alert_type_name=a.alert_type.name,
        org_unit_id=a.org_unit_id,
        org_unit_name=a.org_unit.name,
        severity=a.severity.value,
        state=a.state.value,
        visible_tiers=a.visible_tiers,
        source_event_ref=a.source_event_ref,
        title=a.title,
        detail=a.detail,
        created_at=a.created_at,
        acknowledged_at=a.acknowledged_at,
        resolved_at=a.resolved_at,
    )


@router.get("/", response_model=list[AlertOut])
def list_alerts(
    state: str | None = None,
    severity: str | None = None,
    org_unit_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.auth.dependencies import get_subtree_ids
    allowed_ids = get_subtree_ids(db, current_user.org_unit_id)

    # Visible-tiers filter: include alerts whose visible_tiers include any tier
    # the current user's role would see. Simplified: include all in subtree
    # plus any escalated to the user's tier.
    user_tier = current_user.role.value.replace("_manager", "").replace("_ops", "")

    q = (
        db.query(OpsAlert)
        .join(OpsAlert.alert_type)
        .filter(
            (OpsAlert.org_unit_id.in_(allowed_ids)) |
            (OpsAlert.visible_tiers.contains(user_tier))
        )
    )
    if state:
        q = q.filter(OpsAlert.state == state)
    if severity:
        q = q.filter(OpsAlert.severity == severity)
    if org_unit_id:
        q = q.filter(OpsAlert.org_unit_id == org_unit_id)
    alerts = q.order_by(OpsAlert.created_at.desc()).limit(200).all()
    return [_alert_out(a) for a in alerts]


def _transition(alert: OpsAlert, new_state: OpsAlertState, action: EscalationAction,
                user: User, notes: str | None, db: Session):
    alert.state = new_state
    if new_state == OpsAlertState.ACKNOWLEDGED:
        alert.acknowledged_at = datetime.utcnow()
    elif new_state == OpsAlertState.RESOLVED:
        alert.resolved_at = datetime.utcnow()
    db.add(EscalationEvent(alert_id=alert.id, action=action, actor_user_id=user.id, notes=notes))
    db.commit()
    db.refresh(alert)
    return _alert_out(alert)


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alert = db.get(OpsAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return _transition(alert, OpsAlertState.ACKNOWLEDGED, EscalationAction.ACKNOWLEDGED, current_user, None, db)


@router.post("/{alert_id}/resolve", response_model=AlertOut)
def resolve(alert_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alert = db.get(OpsAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return _transition(alert, OpsAlertState.RESOLVED, EscalationAction.RESOLVED, current_user, None, db)


@router.post("/{alert_id}/escalate", response_model=AlertOut)
def escalate(alert_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.escalation_engine import _next_tier, _add_tier
    alert = db.get(OpsAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    current_tiers = [t.strip() for t in alert.visible_tiers.split(",") if t.strip()]
    next_tier = _next_tier(current_tiers)
    if next_tier:
        alert.visible_tiers = _add_tier(alert.visible_tiers, next_tier)
    return _transition(alert, OpsAlertState.ESCALATED, EscalationAction.ESCALATED_MANUAL, current_user, None, db)


@router.post("/{alert_id}/dismiss", response_model=AlertOut)
def dismiss(alert_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alert = db.get(OpsAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return _transition(alert, OpsAlertState.RESOLVED, EscalationAction.DISMISSED_NOT_USEFUL, current_user,
                       "Dismissed as not useful", db)


@router.post("/check-escalations")
def run_escalations(db: Session = Depends(get_db)):
    """Cron target — call hourly."""
    escalated = check_escalations(db)
    return {"escalated": len(escalated)}


# ── Thresholds ─────────────────────────────────────────────────────────────────

@router.get("/thresholds", response_model=list[ThresholdOut])
def list_thresholds(
    kpi_type: str | None = None,
    org_unit_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(ThresholdConfig)
    if kpi_type:
        q = q.filter(ThresholdConfig.kpi_type == kpi_type)
    if org_unit_id:
        q = q.filter(ThresholdConfig.org_unit_id == org_unit_id)
    return q.order_by(ThresholdConfig.kpi_type).all()


@router.get("/thresholds/effective")
def effective_threshold(
    kpi_type: str,
    org_unit_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cfg = get_effective_threshold(db, kpi_type, org_unit_id)
    if not cfg:
        raise HTTPException(404, "No threshold configured for this KPI and org unit")
    return ThresholdOut(
        id=cfg.id, kpi_type=cfg.kpi_type, org_unit_id=cfg.org_unit_id,
        value=float(cfg.value), direction=cfg.direction.value,
        set_at=cfg.set_at, learned_adjustment=float(cfg.learned_adjustment) if cfg.learned_adjustment else None,
    )


@router.put("/thresholds", response_model=ThresholdOut, status_code=200)
def upsert_threshold(
    payload: ThresholdIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        cfg = set_threshold(
            db=db,
            kpi_type=payload.kpi_type,
            org_unit_id=payload.org_unit_id,
            value=payload.value,
            direction=payload.direction,
            user_id=current_user.id,
        )
    except ThresholdConflict as e:
        raise HTTPException(409, str(e))
    return ThresholdOut(
        id=cfg.id, kpi_type=cfg.kpi_type, org_unit_id=cfg.org_unit_id,
        value=float(cfg.value), direction=cfg.direction.value,
        set_at=cfg.set_at, learned_adjustment=float(cfg.learned_adjustment) if cfg.learned_adjustment else None,
    )
