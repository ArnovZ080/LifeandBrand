"""
Canonical net-sales service (Phase 1).

Levels:
    L0 — gross sales (incl. VAT, before discounts)
    L1 — net of VAT
    L2 — net of VAT and discounts

The current Sale model stores a single amount (``total_revenue``) per site per
business date, written by the ingest pipeline as L2 net sales. Therefore L2 is
computable; L0 and L1 return None until the schema carries gross/VAT/discount
columns.

Non-SITE org units aggregate over their whole subtree (recursive CTE, same
approach as app.auth.dependencies.get_subtree_ids).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_subtree_ids
from app.models import OrgUnit, Sale
from app.models.location import OrgTier


def net_sales(
    db: Session,
    org_unit_id: int,
    date_from: date,
    date_to: date,
    level: str = "L2",
) -> Decimal | None:
    """Sum sales for the org unit (subtree if not a SITE) over [date_from, date_to].

    Returns None when the level cannot be computed from the stored schema or
    when no sales rows exist in the window.
    """
    if level not in ("L0", "L1", "L2"):
        raise ValueError(f"Unknown net sales level: {level}")
    if level in ("L0", "L1"):
        # Sale stores one amount, treated as L2 — gross / net-of-VAT-only are
        # not derivable.
        return None

    unit = db.get(OrgUnit, org_unit_id)
    if unit is None:
        return None
    ids = [unit.id] if unit.tier == OrgTier.SITE else get_subtree_ids(db, unit.id)

    total = db.execute(
        select(func.sum(Sale.total_revenue)).where(
            Sale.location_id.in_(ids),
            Sale.sale_date >= date_from,
            Sale.sale_date <= date_to,
        )
    ).scalar()
    return Decimal(str(total)) if total is not None else None
