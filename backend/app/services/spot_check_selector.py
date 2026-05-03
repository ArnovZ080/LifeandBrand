"""
Spot-check item selection algorithm — v2.

Four scoring signals:

  velocity_score        (20%) — daily sales throughput; fast movers have more
                                 exposure to under-pouring, theft, and waste.

  value_score           (25%) — unit cost of the item. A Dom Perignon sitting
                                 untouched for a week is still a high-risk item
                                 purely because of what it's worth.

  variance_history_score(35%) — average absolute variance % from past spot
                                 checks. Items with a proven track record of
                                 going missing are weighted most heavily.

  recency_score         (20%) — days since last check, capped at CYCLE_DAYS.
                                 Drives rotation fairness.

7-day cycle guarantee:
  Any item not checked within CYCLE_DAYS days is flagged as overdue and
  forced into the session ahead of the scored selection. This ensures every
  active item gets counted at least once per rolling 7-day window, regardless
  of how low it scores on the other signals.

  Session size = max(base_n, len(overdue_items) + 1)
  so overdue items never silently fall through.
"""

from datetime import date, timedelta
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.item import Item, Department
from app.models.sale import Sale, SaleLine
from app.models.recipe import RecipeLine
from app.models.spot_check import SpotCheckSession, SpotCheckItem
from app.models.stock import StockMovement
from app.models.batch import ItemBatch, BatchStatus

BASE_ITEMS_PER_SESSION = 5
CYCLE_DAYS = 7          # every item must be checked within this window
MAX_SESSION_SIZE = 15   # hard cap to keep sessions manageable

VELOCITY_WEIGHT = 0.20
VALUE_WEIGHT = 0.25
VARIANCE_WEIGHT = 0.35
RECENCY_WEIGHT = 0.20

VELOCITY_LOOKBACK_DAYS = 14
VARIANCE_LOOKBACK_DAYS = 30


@dataclass
class ScoredItem:
    item: Item
    total_score: float
    velocity_score: float
    value_score: float
    variance_score: float
    recency_score: float
    days_since_last_check: int
    is_overdue: bool


# ── Signal calculations ────────────────────────────────────────────────────────

def _sales_velocity(db: Session, location_id: int, department: Department, since: date) -> dict[int, float]:
    days = max((date.today() - since).days, 1)
    rows = (
        db.query(RecipeLine.item_id, func.sum(SaleLine.quantity_sold * RecipeLine.quantity_used).label("u"))
        .join(SaleLine, SaleLine.menu_item_id == RecipeLine.menu_item_id)
        .join(Sale, Sale.id == SaleLine.sale_id)
        .join(Item, Item.id == RecipeLine.item_id)
        .filter(Sale.location_id == location_id, Sale.sale_date >= since, Item.department == department)
        .group_by(RecipeLine.item_id).all()
    )
    return {r.item_id: float(r.u) / days for r in rows}


def _variance_history(db: Session, location_id: int, department: Department, since: date) -> dict[int, float]:
    rows = (
        db.query(SpotCheckItem.item_id, func.avg(func.abs(SpotCheckItem.variance_pct)).label("v"))
        .join(SpotCheckSession, SpotCheckSession.id == SpotCheckItem.session_id)
        .join(Item, Item.id == SpotCheckItem.item_id)
        .filter(
            SpotCheckSession.location_id == location_id,
            SpotCheckSession.department == department,
            SpotCheckSession.session_date >= since,
            SpotCheckItem.variance_pct.isnot(None),
        )
        .group_by(SpotCheckItem.item_id).all()
    )
    return {r.item_id: float(r.v) for r in rows}


def _last_check_dates(db: Session, location_id: int, department: Department) -> dict[int, date]:
    rows = (
        db.query(SpotCheckItem.item_id, func.max(SpotCheckSession.session_date).label("d"))
        .join(SpotCheckSession, SpotCheckSession.id == SpotCheckItem.session_id)
        .filter(
            SpotCheckSession.location_id == location_id,
            SpotCheckSession.department == department,
            SpotCheckItem.counted_at.isnot(None),
        )
        .group_by(SpotCheckItem.item_id).all()
    )
    return {r.item_id: r.d for r in rows}


def _normalize(values: list[float]) -> list[float]:
    lo, hi = min(values, default=0), max(values, default=0)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ── Main selection function ────────────────────────────────────────────────────

def select_items_for_session(
    db: Session,
    location_id: int,
    department: Department,
    base_n: int = BASE_ITEMS_PER_SESSION,
    exclude_item_ids: list[int] | None = None,
) -> list[ScoredItem]:
    """
    Select items for a spot-check session.

    Returns overdue items first (sorted by days overdue descending),
    then scored items to fill remaining slots up to max(base_n, overdue_count + 1).
    """
    today = date.today()
    exclude_ids = set(exclude_item_ids or [])

    items = (
        db.query(Item)
        .filter(Item.department == department, Item.is_active == True)
        .all()
    )
    if not items:
        return []

    velocity = _sales_velocity(db, location_id, department, today - timedelta(days=VELOCITY_LOOKBACK_DAYS))
    variance_hist = _variance_history(db, location_id, department, today - timedelta(days=VARIANCE_LOOKBACK_DAYS))
    last_checked = _last_check_dates(db, location_id, department)

    # Raw signal values
    item_ids = [i.id for i in items]
    raw_velocity = [velocity.get(iid, 0.0) for iid in item_ids]
    # Items with no sales get 0 velocity. Items never variance-checked get a 5% default
    # (moderate — neither flagged nor ignored).
    raw_variance = [variance_hist.get(iid, 5.0) for iid in item_ids]
    # Unit cost — use 0 if not set so it doesn't falsely inflate the score
    raw_value = [float(i.unit_cost or 0) for i in items]

    norm_velocity = _normalize(raw_velocity)
    norm_variance = _normalize(raw_variance)
    norm_value = _normalize(raw_value)

    overdue: list[ScoredItem] = []
    scored: list[ScoredItem] = []

    for idx, item in enumerate(items):
        if item.id in exclude_ids:
            continue

        last = last_checked.get(item.id)
        days_ago = min((today - last).days, CYCLE_DAYS) if last else CYCLE_DAYS

        recency_score = days_ago / CYCLE_DAYS
        total = (
            VELOCITY_WEIGHT * norm_velocity[idx]
            + VALUE_WEIGHT * norm_value[idx]
            + VARIANCE_WEIGHT * norm_variance[idx]
            + RECENCY_WEIGHT * recency_score
        )
        overdue_flag = (last is None) or ((today - last).days >= CYCLE_DAYS)

        si = ScoredItem(
            item=item,
            total_score=total,
            velocity_score=norm_velocity[idx],
            value_score=norm_value[idx],
            variance_score=norm_variance[idx],
            recency_score=recency_score,
            days_since_last_check=days_ago if last else CYCLE_DAYS,
            is_overdue=overdue_flag,
        )
        (overdue if overdue_flag else scored).append(si)

    # Overdue items sorted by worst (most days missed) first
    overdue.sort(key=lambda x: x.days_since_last_check, reverse=True)
    scored.sort(key=lambda x: x.total_score, reverse=True)

    # Session size: at minimum cover all overdue items plus at least one scored item,
    # but never exceed MAX_SESSION_SIZE.
    target_n = min(max(base_n, len(overdue) + 1), MAX_SESSION_SIZE)
    fill_slots = max(0, target_n - len(overdue))

    return overdue + scored[:fill_slots]


# ── Theoretical stock helpers ──────────────────────────────────────────────────

def get_theoretical_stock(db: Session, location_id: int, item_id: int) -> float:
    """Current theoretical stock = net of all stock movements."""
    result = (
        db.query(func.sum(StockMovement.quantity))
        .filter(StockMovement.location_id == location_id, StockMovement.item_id == item_id)
        .scalar()
    )
    return float(result or 0)


def get_active_batches(db: Session, location_id: int, item_id: int) -> list[ItemBatch]:
    """
    Active and expiring-soon batches for a perishable item, ordered oldest first
    (FIFO order — the batch expiring soonest should be counted and consumed first).
    """
    return (
        db.query(ItemBatch)
        .filter(
            ItemBatch.location_id == location_id,
            ItemBatch.item_id == item_id,
            ItemBatch.status.in_([BatchStatus.ACTIVE, BatchStatus.EXPIRING_SOON]),
        )
        .order_by(ItemBatch.best_before_date.asc().nulls_last(), ItemBatch.received_date.asc())
        .all()
    )
