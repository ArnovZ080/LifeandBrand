"""
Accuracy Ledger service (Phase 0/1).

A metric earns "green" for an org unit once its last `required_green_periods`
resolved entries (ground truth present) are all within tolerance. A single
out-of-tolerance latest resolved entry makes it "red". Anything else —
including no resolved entries yet — is "pending".
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, Metric


def ensure_metric(
    db: Session,
    key: str,
    name: str,
    tolerance_pct: float,
    required_green_periods: int,
) -> Metric:
    """Idempotent get-or-create of a ledger metric by key."""
    metric = db.execute(select(Metric).where(Metric.key == key)).scalars().first()
    if metric is None:
        metric = Metric(
            key=key, name=name,
            tolerance_pct=tolerance_pct,
            required_green_periods=required_green_periods,
        )
        db.add(metric)
        db.commit()
        db.refresh(metric)
    return metric


def record_entry(
    db: Session,
    metric_key: str,
    org_unit_id: int,
    period_date: date,
    computed_value,
    ground_truth_value=None,
) -> LedgerEntry:
    """Upsert the ledger entry for (metric, org_unit, period_date).

    within_tolerance is set as soon as ground truth is present:
    |computed - truth| / |truth| * 100 <= metric.tolerance_pct
    (truth of exactly 0 requires computed of exactly 0).
    """
    metric = db.execute(select(Metric).where(Metric.key == metric_key)).scalars().first()
    if metric is None:
        raise ValueError(f"Unknown ledger metric: {metric_key}")

    entry = db.execute(
        select(LedgerEntry).where(
            LedgerEntry.metric_id == metric.id,
            LedgerEntry.org_unit_id == org_unit_id,
            LedgerEntry.period_date == period_date,
        )
    ).scalars().first()
    if entry is None:
        entry = LedgerEntry(metric_id=metric.id, org_unit_id=org_unit_id, period_date=period_date,
                            computed_value=computed_value)
        db.add(entry)
    else:
        entry.computed_value = computed_value

    if ground_truth_value is not None:
        entry.ground_truth_value = ground_truth_value
        truth = float(ground_truth_value)
        computed = float(computed_value)
        if truth == 0:
            entry.within_tolerance = computed == 0
        else:
            deviation_pct = abs(computed - truth) / abs(truth) * 100.0
            entry.within_tolerance = deviation_pct <= float(metric.tolerance_pct)

    db.commit()
    db.refresh(entry)
    return entry


def ledger_status(db: Session, metric_key: str, org_unit_id: int) -> str:
    """'red' | 'green' | 'pending' — see module docstring."""
    metric = db.execute(select(Metric).where(Metric.key == metric_key)).scalars().first()
    if metric is None:
        return "pending"

    resolved = db.execute(
        select(LedgerEntry.within_tolerance)
        .where(
            LedgerEntry.metric_id == metric.id,
            LedgerEntry.org_unit_id == org_unit_id,
            LedgerEntry.within_tolerance.is_not(None),
        )
        .order_by(LedgerEntry.period_date.desc())
        .limit(metric.required_green_periods)
    ).scalars().all()

    if not resolved:
        return "pending"
    if resolved[0] is False:
        return "red"
    if len(resolved) >= metric.required_green_periods and all(resolved):
        return "green"
    return "pending"
