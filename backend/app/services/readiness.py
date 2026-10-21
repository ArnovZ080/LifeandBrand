"""
Readiness gate for predictive ordering (Feature 4).

readiness(db, org_unit_id, as_of) returns one dict per check:
{name, passed, detail}. The site is ready only when every check passed.

Windows are inclusive and counted back from as_of. Sales days are days with
at least one item-level sales line.

  sales_history        STRICT. At least 28 sales days in the last 60 days.
  recent_stock_count   STRICT. A submitted StockCount for the site dated within the last 14 days.
  recipes_cover_sales  THRESHOLD. At least 80% of item units sold in the last 28 days belong
                       to a menu item with a recipe in force on as_of.
  suppliers_linked     STRICT. Every ingredient of a recipe in force on as_of, for a menu
                       item sold in the last 14 days, has an active SupplierItem.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.stock_count import StockCount, StockCountStatus
from app.models.supplier import SupplierItem
from app.services.forecast_service import MIN_SALES_DAYS, daily_sales, effective_recipe_lines

SALES_HISTORY_DAYS = 60
STOCK_COUNT_DAYS = 14
COVERAGE_DAYS = 28
COVERAGE_THRESHOLD = Decimal("0.80")
SUPPLIER_DAYS = 14


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def readiness(db: Session, org_unit_id: int, as_of: date) -> list[dict]:
    return [
        _sales_history(db, org_unit_id, as_of),
        _recent_stock_count(db, org_unit_id, as_of),
        _recipes_cover_sales(db, org_unit_id, as_of),
        _suppliers_linked(db, org_unit_id, as_of),
    ]


def is_ready(checks: list[dict]) -> bool:
    return all(check["passed"] for check in checks)


def _sales_history(db: Session, org_unit_id: int, as_of: date) -> dict:
    days = len(daily_sales(db, org_unit_id, as_of - timedelta(days=SALES_HISTORY_DAYS - 1), as_of))
    return _check(
        "sales_history", days >= MIN_SALES_DAYS,
        f"{days} sales day(s) in the last {SALES_HISTORY_DAYS} days; {MIN_SALES_DAYS} required",
    )


def _recent_stock_count(db: Session, org_unit_id: int, as_of: date) -> dict:
    latest = db.execute(
        select(func.max(StockCount.count_date)).where(
            StockCount.org_unit_id == org_unit_id,
            StockCount.status == StockCountStatus.SUBMITTED,
            StockCount.count_date >= as_of - timedelta(days=STOCK_COUNT_DAYS - 1),
            StockCount.count_date <= as_of,
        )
    ).scalar()
    if latest is None:
        return _check("recent_stock_count", False,
                      f"no submitted stock count in the last {STOCK_COUNT_DAYS} days")
    return _check("recent_stock_count", True, f"latest submitted stock count dated {latest.isoformat()}")


def _recipes_cover_sales(db: Session, org_unit_id: int, as_of: date) -> dict:
    sales = daily_sales(db, org_unit_id, as_of - timedelta(days=COVERAGE_DAYS - 1), as_of)
    volume: dict[int, Decimal] = {}
    for day_sales in sales.values():
        for menu_item_id, quantity in day_sales.items():
            volume[menu_item_id] = volume.get(menu_item_id, Decimal(0)) + quantity
    total = sum(volume.values(), Decimal(0))
    if total <= 0:
        return _check("recipes_cover_sales", False,
                      f"no item sales in the last {COVERAGE_DAYS} days")
    covered_ids = set(effective_recipe_lines(db, volume.keys(), as_of))
    covered = sum((volume[mid] for mid in covered_ids), Decimal(0))
    share = covered / total
    return _check(
        "recipes_cover_sales", share >= COVERAGE_THRESHOLD,
        f"{share * 100:.1f}% of {format(total.normalize(), 'f')} units sold in the last {COVERAGE_DAYS} days "
        f"have a current recipe; {COVERAGE_THRESHOLD * 100:.0f}% required",
    )


def _suppliers_linked(db: Session, org_unit_id: int, as_of: date) -> dict:
    sales = daily_sales(db, org_unit_id, as_of - timedelta(days=SUPPLIER_DAYS - 1), as_of)
    menu_item_ids = {mid for day_sales in sales.values() for mid in day_sales}
    if not menu_item_ids:
        return _check("suppliers_linked", False, f"no item sales in the last {SUPPLIER_DAYS} days")
    ingredient_ids = {
        line.item_id
        for lines in effective_recipe_lines(db, menu_item_ids, as_of).values()
        for line in lines
    }
    if not ingredient_ids:
        return _check("suppliers_linked", False,
                      f"no recipe ingredients for items sold in the last {SUPPLIER_DAYS} days")
    linked = set(db.execute(
        select(SupplierItem.item_id).where(
            SupplierItem.item_id.in_(ingredient_ids),
            SupplierItem.is_active.is_(True),
        ).distinct()
    ).scalars())
    missing = sorted(ingredient_ids - linked)
    if not missing:
        return _check("suppliers_linked", True,
                      f"all {len(ingredient_ids)} recipe ingredient(s) have a supplier")
    codes = list(db.execute(select(Item.code).where(Item.id.in_(missing)).order_by(Item.code)).scalars())
    return _check("suppliers_linked", False,
                  f"{len(missing)} ingredient(s) have no supplier: {', '.join(codes)}")
