"""
Rule-based COS variance cause classifier (Phase 2).

Deterministic, ordered rules — the first that matches wins:

1. counting_swap    — another flag at the same unit/period on an item in the
                      SAME category has a variance value of opposite sign and
                      similar magnitude (within 25%). Classic "counted the
                      Absolut as the Smirnoff" swap.
2. timing           — the same item's previous-period flag has an
                      opposite-sign variance of similar magnitude (within
                      25%): a delivery/count landed either side of month end.
3. spillage         — perishable ("high-prep") item with a small positive
                      usage variance (actual > theoretical, |value| < 2x the
                      flag threshold) in this AND at least the two previous
                      periods.
4. process_failure  — same-direction variance on the same item in >= 3
                      consecutive periods (this one plus the two before),
                      regardless of size.
5. immediate        — single large spike: |variance value| >= 5x the flag
                      threshold with no flag on this item in the previous two
                      periods.
6. known_baseline   — a dismissed flag exists for the same item at the same
                      unit within the last 3 periods.
Otherwise None (unclassified — needs a human).

Sign convention: variance = actual - theoretical, so positive = unexplained
consumption/shrinkage, negative = less used than recipes predict.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Item
from app.models.cos_flag import CosCause, CosFlag

SIMILARITY = Decimal("0.25")  # magnitudes within 25% count as "similar"


def prev_period(period: str, n: int = 1) -> str:
    """'YYYY-MM' n months earlier."""
    year, month = int(period[:4]), int(period[5:7])
    total = year * 12 + (month - 1) - n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _similar_magnitude(a: Decimal, b: Decimal) -> bool:
    a, b = abs(a), abs(b)
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(a, b) <= SIMILARITY


def build_context(db: Session, flag: CosFlag) -> dict:
    """Collect the history the rules need for one flag."""
    item = db.get(Item, flag.item_id)

    sibling_flags = db.execute(
        select(CosFlag)
        .join(Item, CosFlag.item_id == Item.id)
        .where(
            CosFlag.org_unit_id == flag.org_unit_id,
            CosFlag.period == flag.period,
            CosFlag.item_id != flag.item_id,
            Item.category == (item.category if item else None),
        )
    ).scalars().all()

    lookback = [prev_period(flag.period, n) for n in (1, 2, 3)]
    prior_flags = db.execute(
        select(CosFlag).where(
            CosFlag.org_unit_id == flag.org_unit_id,
            CosFlag.item_id == flag.item_id,
            CosFlag.period.in_(lookback),
        )
    ).scalars().all()
    by_period = {f.period: f for f in prior_flags}

    return {
        "item": item,
        "sibling_flags": sibling_flags,                      # same category, same period
        "prev1": by_period.get(lookback[0]),                 # previous period's flag
        "prev2": by_period.get(lookback[1]),
        "dismissed_recent": any(f.status == "dismissed" for f in prior_flags),
    }


def classify(flag: CosFlag, context: dict) -> CosCause | None:
    """Apply the ordered rules from the module docstring. Pure function of
    the flag + context — no DB access, fully deterministic."""
    v = Decimal(str(flag.variance_value)) if flag.variance_value is not None else None
    if v is None:
        return None
    threshold = Decimal(str(settings.cos_flag_threshold_value))
    item: Item | None = context.get("item")
    prev1: CosFlag | None = context.get("prev1")
    prev2: CosFlag | None = context.get("prev2")

    # 1. Offsetting variance on a similar (same-category) item → counting swap
    for sibling in context.get("sibling_flags", []):
        if sibling.variance_value is None:
            continue
        sv = Decimal(str(sibling.variance_value))
        if (sv > 0) != (v > 0) and _similar_magnitude(sv, v):
            return CosCause.COUNTING_SWAP

    # 2. Reversal vs the previous period → timing
    if prev1 is not None and prev1.variance_value is not None:
        pv = Decimal(str(prev1.variance_value))
        if (pv > 0) != (v > 0) and _similar_magnitude(pv, v):
            return CosCause.TIMING

    def same_direction(other: CosFlag | None) -> bool:
        return (other is not None and other.variance_value is not None
                and (Decimal(str(other.variance_value)) > 0) == (v > 0))

    persistent_3 = same_direction(prev1) and same_direction(prev2)

    # 3. Small persistent shrinkage on high-prep (perishable) items → spillage
    if (item is not None and item.is_perishable
            and v > 0 and abs(v) < 2 * threshold and persistent_3):
        return CosCause.SPILLAGE

    # 4. Recurring same-direction variance >= 3 consecutive periods
    if persistent_3:
        return CosCause.PROCESS_FAILURE

    # 5. Single large spike with no recent history
    if abs(v) >= 5 * threshold and prev1 is None and prev2 is None:
        return CosCause.IMMEDIATE

    # 6. Previously dismissed for this item recently → known baseline
    if context.get("dismissed_recent"):
        return CosCause.KNOWN_BASELINE

    return None
