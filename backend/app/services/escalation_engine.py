"""
Escalation state machine (§4.5 of design spec).

Rules:
  OPEN with no acknowledgment for > 48h → ESCALATED + auto-escalation event
  ACKNOWLEDGED with no resolution for > 48h → ESCALATED + auto-escalation event
  Escalation widens visible_tiers without removing existing tiers.

Tier widening order: site → area → regional → national → md → ceo
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.operational_alert import OpsAlert, OpsAlertState, EscalationEvent, EscalationAction

ESCALATION_WINDOW_HOURS = 48

TIER_ORDER = ["site", "area", "regional", "national", "md", "ceo"]


def _next_tier(current_tiers: list[str]) -> str | None:
    max_idx = max((TIER_ORDER.index(t) for t in current_tiers if t in TIER_ORDER), default=-1)
    next_idx = max_idx + 1
    return TIER_ORDER[next_idx] if next_idx < len(TIER_ORDER) else None


def _add_tier(visible_tiers_str: str, new_tier: str) -> str:
    tiers = {t.strip() for t in visible_tiers_str.split(",") if t.strip()}
    tiers.add(new_tier)
    return ",".join(sorted(tiers, key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 99))


def check_escalations(db: Session) -> list[OpsAlert]:
    """
    Called hourly by the cron endpoint.
    Returns the list of alerts that were escalated this run.
    """
    cutoff = datetime.utcnow() - timedelta(hours=ESCALATION_WINDOW_HOURS)
    escalated = []

    # OPEN alerts older than the window with no acknowledgment
    open_stale = (
        db.query(OpsAlert)
        .filter(OpsAlert.state == OpsAlertState.OPEN, OpsAlert.created_at <= cutoff)
        .all()
    )

    # ACKNOWLEDGED alerts older than the window since acknowledgment with no resolution
    ack_stale = (
        db.query(OpsAlert)
        .filter(
            OpsAlert.state == OpsAlertState.ACKNOWLEDGED,
            OpsAlert.acknowledged_at <= cutoff,
        )
        .all()
    )

    for alert in open_stale + ack_stale:
        current_tiers = [t.strip() for t in alert.visible_tiers.split(",") if t.strip()]
        next_tier = _next_tier(current_tiers)
        if next_tier:
            alert.visible_tiers = _add_tier(alert.visible_tiers, next_tier)
        alert.state = OpsAlertState.ESCALATED
        db.add(EscalationEvent(
            alert_id=alert.id,
            action=EscalationAction.ESCALATED_AUTO,
            actor_user_id=None,
            notes=f"Auto-escalated after {ESCALATION_WINDOW_HOURS}h without action",
        ))
        escalated.append(alert)

    db.commit()
    return escalated
