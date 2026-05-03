from datetime import date
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.models.stock import StockMovement, StockTake, StockTakeLine, MovementType
from app.models.sale import Sale, SaleLine
from app.models.recipe import RecipeLine
from app.models.item import Item


@dataclass
class ItemVariance:
    item_id: int
    item_code: str
    item_name: str
    opening_stock: float
    stock_in: float           # deliveries
    theoretical_usage: float  # from sales × recipes
    theoretical_closing: float
    actual_closing: float
    variance_quantity: float  # actual - theoretical (negative = loss)
    unit_cost: float
    variance_value: float


def calculate_theoretical_usage(
    db: Session,
    location_id: int,
    from_date: date,
    to_date: date,
) -> dict[int, float]:
    """
    Returns {item_id: total_theoretical_usage} for the period.
    Joins sale_lines → menu_items → recipe_lines to sum consumption.
    """
    rows = (
        db.query(
            RecipeLine.item_id,
            func.sum(SaleLine.quantity_sold * RecipeLine.quantity_used).label("usage"),
        )
        .join(SaleLine, SaleLine.menu_item_id == RecipeLine.menu_item_id)
        .join(Sale, Sale.id == SaleLine.sale_id)
        .filter(
            Sale.location_id == location_id,
            Sale.sale_date >= from_date,
            Sale.sale_date <= to_date,
        )
        .group_by(RecipeLine.item_id)
        .all()
    )
    return {row.item_id: float(row.usage) for row in rows}


def calculate_stock_in(
    db: Session,
    location_id: int,
    from_date: date,
    to_date: date,
) -> dict[int, float]:
    """Returns {item_id: total_units_received} for the period."""
    rows = (
        db.query(
            StockMovement.item_id,
            func.sum(StockMovement.quantity).label("total"),
        )
        .filter(
            StockMovement.location_id == location_id,
            StockMovement.movement_type == MovementType.DELIVERY,
            func.date(StockMovement.created_at) >= from_date,
            func.date(StockMovement.created_at) <= to_date,
        )
        .group_by(StockMovement.item_id)
        .all()
    )
    return {row.item_id: float(row.total) for row in rows}


def get_opening_stock(
    db: Session,
    location_id: int,
    before_date: date,
) -> dict[int, float]:
    """
    Opening stock = sum of all movements before the period start.
    Uses the stock_take closest before from_date as the base if available,
    then adds movements since that take.
    """
    rows = (
        db.query(
            StockMovement.item_id,
            func.sum(StockMovement.quantity).label("total"),
        )
        .filter(
            StockMovement.location_id == location_id,
            func.date(StockMovement.created_at) < before_date,
        )
        .group_by(StockMovement.item_id)
        .all()
    )
    return {row.item_id: float(row.total) for row in rows}


def build_variance_report(
    db: Session,
    stock_take_id: int,
) -> list[ItemVariance]:
    """
    Produces a full variance report for a finalised stock take.
    Compares theoretical closing stock against actual counted stock.
    """
    stock_take = db.get(StockTake, stock_take_id)
    if stock_take is None:
        raise ValueError(f"StockTake {stock_take_id} not found")

    location_id = stock_take.location_id
    take_date = stock_take.take_date

    # Find the previous finalised stock take to establish the period
    previous_take = (
        db.query(StockTake)
        .filter(
            StockTake.location_id == location_id,
            StockTake.is_finalised == True,
            StockTake.take_date < take_date,
        )
        .order_by(StockTake.take_date.desc())
        .first()
    )
    period_start = previous_take.take_date if previous_take else date(2000, 1, 1)

    opening = get_opening_stock(db, location_id, period_start)
    stock_in = calculate_stock_in(db, location_id, period_start, take_date)
    theoretical_usage = calculate_theoretical_usage(db, location_id, period_start, take_date)

    # Build a map from actual counts
    actual_counts = {
        line.item_id: (float(line.actual_quantity), float(line.unit_cost or 0))
        for line in stock_take.lines
    }

    all_item_ids = set(opening) | set(stock_in) | set(theoretical_usage) | set(actual_counts)

    results = []
    for item_id in all_item_ids:
        item = db.get(Item, item_id)
        if item is None:
            continue

        open_qty = opening.get(item_id, 0)
        in_qty = stock_in.get(item_id, 0)
        theoretical = theoretical_usage.get(item_id, 0)
        theoretical_closing = open_qty + in_qty - theoretical

        actual_closing, unit_cost = actual_counts.get(item_id, (0, 0))
        variance_qty = actual_closing - theoretical_closing
        variance_val = variance_qty * unit_cost

        results.append(ItemVariance(
            item_id=item_id,
            item_code=item.code,
            item_name=item.name,
            opening_stock=open_qty,
            stock_in=in_qty,
            theoretical_usage=theoretical,
            theoretical_closing=theoretical_closing,
            actual_closing=actual_closing,
            variance_quantity=variance_qty,
            unit_cost=unit_cost,
            variance_value=variance_val,
        ))

    results.sort(key=lambda x: x.variance_value)  # worst losses first
    return results
