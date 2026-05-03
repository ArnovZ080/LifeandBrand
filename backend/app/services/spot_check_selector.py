"""
Spot-check item selection algorithm.

Scores each item in a department using three signals:

  sales_velocity_score  — how fast this item moves (high turnover = more exposure)
  variance_history_score — how often/badly this item has shown up as a problem
  recency_score         — how long since it was last spot-checked (rotation fairness)

  total_score = 0.30 * velocity + 0.50 * variance_history + 0.20 * recency

Variance is weighted highest: we care most about items with a proven track record
of going missing, being short-poured, or being mis-received.
"""

from datetime import date, timedelta
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.item import Item, Department
from app.models.sale import Sale, SaleLine
from app.models.recipe import RecipeLine
from app.models.spot_check import SpotCheckSession, SpotCheckItem
from app.models.stock import StockMovement, MovementType


ITEMS_PER_SESSION = 5
VELOCITY_WEIGHT = 0.30
VARIANCE_WEIGHT = 0.50
RECENCY_WEIGHT = 0.20
VARIANCE_LOOKBACK_DAYS = 30
VELOCITY_LOOKBACK_DAYS = 14
MAX_RECENCY_DAYS = 14  # after 14 days without a check, recency score maxes out


@dataclass
class ScoredItem:
    item: Item
    total_score: float
    velocity_score: float
    variance_score: float
    recency_score: float
    days_since_last_check: int


def _get_sales_velocity(
    db: Session,
    location_id: int,
    department: Department,
    since: date,
) -> dict[int, float]:
    """Average daily theoretical usage per item over the lookback window."""
    days = (date.today() - since).days or 1
    rows = (
        db.query(
            RecipeLine.item_id,
            func.sum(SaleLine.quantity_sold * RecipeLine.quantity_used).label("total_usage"),
        )
        .join(SaleLine, SaleLine.menu_item_id == RecipeLine.menu_item_id)
        .join(Sale, Sale.id == SaleLine.sale_id)
        .join(Item, Item.id == RecipeLine.item_id)
        .filter(
            Sale.location_id == location_id,
            Sale.sale_date >= since,
            Item.department == department,
        )
        .group_by(RecipeLine.item_id)
        .all()
    )
    return {row.item_id: float(row.total_usage) / days for row in rows}


def _get_variance_history(
    db: Session,
    location_id: int,
    department: Department,
    since: date,
) -> dict[int, float]:
    """
    Average absolute variance percentage per item from past spot checks.
    Items never checked get a moderate default score to ensure they enter rotation.
    """
    rows = (
        db.query(
            SpotCheckItem.item_id,
            func.avg(func.abs(SpotCheckItem.variance_pct)).label("avg_variance_pct"),
        )
        .join(SpotCheckSession, SpotCheckSession.id == SpotCheckItem.session_id)
        .join(Item, Item.id == SpotCheckItem.item_id)
        .filter(
            SpotCheckSession.location_id == location_id,
            SpotCheckSession.department == department,
            SpotCheckSession.session_date >= since,
            SpotCheckItem.variance_pct.isnot(None),
        )
        .group_by(SpotCheckItem.item_id)
        .all()
    )
    return {row.item_id: float(row.avg_variance_pct) for row in rows}


def _get_last_check_dates(
    db: Session,
    location_id: int,
    department: Department,
) -> dict[int, date]:
    """Most recent check date per item."""
    rows = (
        db.query(
            SpotCheckItem.item_id,
            func.max(SpotCheckSession.session_date).label("last_date"),
        )
        .join(SpotCheckSession, SpotCheckSession.id == SpotCheckItem.session_id)
        .filter(
            SpotCheckSession.location_id == location_id,
            SpotCheckSession.department == department,
            SpotCheckItem.counted_at.isnot(None),  # only sessions where a count was actually submitted
        )
        .group_by(SpotCheckItem.item_id)
        .all()
    )
    return {row.item_id: row.last_date for row in rows}


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalise to [0, 1]. Returns zeros if all values identical."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def select_items_for_session(
    db: Session,
    location_id: int,
    department: Department,
    n: int = ITEMS_PER_SESSION,
    exclude_item_ids: list[int] | None = None,
) -> list[ScoredItem]:
    """
    Select the top-N items for a spot-check session.
    Pass exclude_item_ids to avoid repeating the morning session's items in the afternoon.
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

    velocity = _get_sales_velocity(db, location_id, department, today - timedelta(days=VELOCITY_LOOKBACK_DAYS))
    variance_hist = _get_variance_history(db, location_id, department, today - timedelta(days=VARIANCE_LOOKBACK_DAYS))
    last_checked = _get_last_check_dates(db, location_id, department)

    item_ids = [i.id for i in items]
    raw_velocity = [velocity.get(iid, 0.0) for iid in item_ids]
    # Items never checked get a mid-range default variance score (0.05 = 5%)
    raw_variance = [variance_hist.get(iid, 5.0) for iid in item_ids]

    norm_velocity = _normalize(raw_velocity)
    norm_variance = _normalize(raw_variance)

    scored: list[ScoredItem] = []
    for idx, item in enumerate(items):
        if item.id in exclude_ids:
            continue

        last = last_checked.get(item.id)
        if last is None:
            days_ago = MAX_RECENCY_DAYS  # never checked — max recency score
        else:
            days_ago = min((today - last).days, MAX_RECENCY_DAYS)

        recency_score = days_ago / MAX_RECENCY_DAYS

        total = (
            VELOCITY_WEIGHT * norm_velocity[idx]
            + VARIANCE_WEIGHT * norm_variance[idx]
            + RECENCY_WEIGHT * recency_score
        )

        scored.append(ScoredItem(
            item=item,
            total_score=total,
            velocity_score=norm_velocity[idx],
            variance_score=norm_variance[idx],
            recency_score=recency_score,
            days_since_last_check=days_ago,
        ))

    scored.sort(key=lambda x: x.total_score, reverse=True)
    return scored[:n]


def get_theoretical_stock(
    db: Session,
    location_id: int,
    item_id: int,
) -> float:
    """
    Current theoretical stock = sum of all stock movements for this item at this location.
    Deliveries are positive, sales/waste/transfers-out are negative.
    """
    result = (
        db.query(func.sum(StockMovement.quantity))
        .filter(
            StockMovement.location_id == location_id,
            StockMovement.item_id == item_id,
        )
        .scalar()
    )
    return float(result or 0)
