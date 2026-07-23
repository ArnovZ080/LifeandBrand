"""
Expiry alert engine.

Called by the /alerts/trigger endpoint (run via cron or manually from dashboard).

Logic:
  1. Find all active/expiring-soon batches across all locations
  2. For each batch, determine which alert level applies (48h / 24h / same-day)
  3. Find contacts subscribed to that batch's department
  4. Skip contacts already alerted at this level today
  5. Skip contacts in quiet hours
  6. Send via each of their active channels
  7. Record the result in ExpiryAlert
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from app.models.batch import ItemBatch, BatchStatus
from app.models.contact import LocationContact, NotificationChannel
from app.models.alert import ExpiryAlert, AlertLevel, AlertStatus
from app.models.operational_alert import OpsAlert, OpsAlertState, OpsSeverity
from app.services.notifications import build_message, send_email, send_teams, send_whatsapp

# Alert fires when hours_until_expiry <= threshold
ALERT_THRESHOLDS = [
    AlertLevel.URGENT,   # 0h  — expires today
    AlertLevel.ACTION,   # 24h
    AlertLevel.WARNING,  # 48h
]


@dataclass
class AlertResult:
    batch_id: int
    contact_name: str
    channel: str
    status: str
    item_name: str
    batch_reference: str


def _hours_until_expiry(best_before: date) -> int:
    delta = datetime.combine(best_before, datetime.max.time()) - datetime.utcnow()
    return max(0, int(delta.total_seconds() / 3600))


def _applicable_level(hours_left: int) -> int | None:
    """Return the most specific alert level that applies, or None."""
    for level in ALERT_THRESHOLDS:
        if hours_left <= level:
            return level
    return None


def _already_alerted_today(db: Session, batch_id: int, contact_id: int, level: int) -> bool:
    today = date.today()
    return db.query(ExpiryAlert).filter(
        ExpiryAlert.batch_id == batch_id,
        ExpiryAlert.contact_id == contact_id,
        ExpiryAlert.alert_level == level,
        ExpiryAlert.sent_at >= datetime(today.year, today.month, today.day),
        ExpiryAlert.status == AlertStatus.SENT,
    ).first() is not None


def _in_quiet_hours(contact: LocationContact) -> bool:
    hour = datetime.now().hour
    start, end = contact.quiet_hours_start, contact.quiet_hours_end
    if start > end:  # wraps midnight e.g. 22:00–07:00
        return hour >= start or hour < end
    return start <= hour < end


def _dispatch(contact: LocationContact, msg, channel: NotificationChannel) -> bool:
    if channel == NotificationChannel.EMAIL and contact.email:
        return send_email(contact.email, msg)
    if channel == NotificationChannel.TEAMS and contact.teams_webhook_url:
        return send_teams(contact.teams_webhook_url, msg)
    if channel == NotificationChannel.WHATSAPP and contact.whatsapp_number:
        return send_whatsapp(contact.whatsapp_number, msg)
    return False


def run_alert_check(db: Session, location_id: int | None = None) -> list[AlertResult]:
    """
    Main entry point. Pass location_id to run for one location only.
    Returns a list of AlertResult describing every alert attempted.
    """
    results: list[AlertResult] = []

    # Fetch all active / expiring-soon batches
    q = db.query(ItemBatch).filter(
        ItemBatch.best_before_date.isnot(None),
        ItemBatch.status.in_([BatchStatus.ACTIVE, BatchStatus.EXPIRING_SOON]),
        ItemBatch.quantity_remaining > 0,
    )
    if location_id:
        q = q.filter(ItemBatch.location_id == location_id)
    batches = q.all()

    for batch in batches:
        # Refresh status
        batch.refresh_status()

        hours_left = _hours_until_expiry(batch.best_before_date)
        level = _applicable_level(hours_left)
        if level is None:
            continue  # more than 48h away — no alert yet

        dept = batch.item.department.value

        # Find contacts subscribed to this department at this location
        contacts = (
            db.query(LocationContact)
            .filter(
                LocationContact.location_id == batch.location_id,
                LocationContact.is_active == True,
            )
            .all()
        )
        # Filter to those subscribed to this department
        relevant_contacts = [c for c in contacts if dept in c.department_list() or not c.departments_subscribed]

        item_name = batch.item.name
        unit = batch.item.unit_of_measure.abbreviation
        msg = build_message(
            item_name=item_name,
            batch_reference=batch.batch_reference or f"Batch {batch.id}",
            quantity_remaining=float(batch.quantity_remaining),
            unit=unit,
            best_before_date=str(batch.best_before_date),
            days_until_expiry=hours_left,
        )

        for contact in relevant_contacts:
            if _in_quiet_hours(contact):
                db.add(ExpiryAlert(
                    batch_id=batch.id,
                    contact_id=contact.id,
                    alert_level=level,
                    channel=NotificationChannel.EMAIL,
                    status=AlertStatus.SUPPRESSED,
                    message_preview=msg.subject,
                ))
                continue

            for channel in contact.channel_list():
                if _already_alerted_today(db, batch.id, contact.id, level):
                    continue

                success = _dispatch(contact, msg, channel)
                status = AlertStatus.SENT if success else AlertStatus.FAILED

                db.add(ExpiryAlert(
                    batch_id=batch.id,
                    contact_id=contact.id,
                    alert_level=level,
                    channel=channel,
                    status=status,
                    message_preview=msg.subject[:300],
                ))

                results.append(AlertResult(
                    batch_id=batch.id,
                    contact_name=contact.name,
                    channel=channel.value,
                    status=status.value,
                    item_name=item_name,
                    batch_reference=batch.batch_reference or "",
                ))

    # Phase 1 shadow mode: publish generalised OpsAlert rows alongside ExpiryAlerts.
    # The ops_alert_types table must be seeded before this runs.
    _publish_ops_alerts(db, batches)

    db.commit()
    return results


def _publish_ops_alerts(db: Session, batches: list[ItemBatch]) -> None:
    """
    Write OpsAlert rows for each expiry event so the new alerting layer
    can observe them in parallel with the existing ExpiryAlert system.
    Skips quietly if the freshness_expiry alert type hasn't been seeded yet.
    """
    from app.models.operational_alert import OpsAlertType
    alert_type = db.query(OpsAlertType).filter(OpsAlertType.key == "freshness_expiry").first()
    if not alert_type:
        return

    today_str = str(__import__("datetime").date.today())
    for batch in batches:
        hours_left = _hours_until_expiry(batch.best_before_date)
        level = _applicable_level(hours_left)
        if level is None:
            continue

        severity = OpsSeverity.CRITICAL if level == AlertLevel.URGENT else (
            OpsSeverity.HIGH if level == AlertLevel.ACTION else OpsSeverity.MEDIUM
        )
        ref = f"expiry_alert:batch:{batch.id}:{today_str}"

        existing = db.query(OpsAlert).filter(OpsAlert.source_event_ref == ref).first()
        if existing:
            continue

        db.add(OpsAlert(
            alert_type_id=alert_type.id,
            org_unit_id=batch.location_id,
            severity=severity,
            state=OpsAlertState.OPEN,
            visible_tiers="site",
            source_event_ref=ref,
            title=f"Expiry: {batch.item.name} — {hours_left}h remaining",
            detail=(
                f"Batch {batch.batch_reference or batch.id}: "
                f"{float(batch.quantity_remaining)} {batch.item.unit_of_measure.abbreviation} "
                f"best before {batch.best_before_date}"
            ),
        ))
