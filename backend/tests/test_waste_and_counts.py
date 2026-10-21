"""Tests for wastage logging and stock-count variance (Feature 1).

Runs on an in-memory SQLite engine. Nothing here is Postgres-only: the enum
columns, JSON item_ids and the recursive subtree CTE all work on SQLite.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models import (
    Item, OrgTier, OrgUnit, StockCountStatus, StockMovement, UnitOfMeasure, WasteReason,
)
from app.models.stock import MovementType
from app.services.cos_service import compute_variance
from app.services.spot_check_selector import get_theoretical_stock
from app.services.stock_count_service import (
    count_variance_summary, create_count, create_template, period_count_variance,
    record_counts, submit_count,
)
from app.services.waste_service import log_waste, waste_summary


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def world(db):
    """One area with two sites, three items (steak, wine, salt; salt has no cost)."""
    uom = UnitOfMeasure(name="each", abbreviation="ea")
    db.add(uom)
    db.flush()

    area = OrgUnit(name="North", tier=OrgTier.AREA)
    db.add(area)
    db.flush()
    site_a = OrgUnit(name="Site A", tier=OrgTier.SITE, parent_id=area.id)
    site_b = OrgUnit(name="Site B", tier=OrgTier.SITE, parent_id=area.id)
    db.add_all([site_a, site_b])
    db.flush()

    steak = Item(code="STK", name="Steak", category="meat", unit_of_measure_id=uom.id, unit_cost=4.50)
    wine = Item(code="WNE", name="House red", category="bar", unit_of_measure_id=uom.id, unit_cost=12.00)
    salt = Item(code="SLT", name="Salt", category="dry", unit_of_measure_id=uom.id, unit_cost=None)
    db.add_all([steak, wine, salt])
    db.commit()
    return {"area": area, "site_a": site_a, "site_b": site_b,
            "steak": steak, "wine": wine, "salt": salt}


def _opening(db, unit, item, qty):
    db.add(StockMovement(location_id=unit.id, item_id=item.id,
                         movement_type=MovementType.OPENING, quantity=qty))
    db.commit()


def _waste_movement(db, event_id):
    return db.execute(
        select(StockMovement).where(
            StockMovement.reference_type == "waste_event",
            StockMovement.reference_id == event_id,
        )
    ).scalar_one()


# ── Waste ──────────────────────────────────────────────────────────────────────

def test_waste_logging_creates_negative_movement_with_snapshot_cost(db, world):
    site, steak = world["site_a"], world["steak"]
    _opening(db, site, steak, 10)

    event = log_waste(db, org_unit_id=site.id, item_id=steak.id, quantity=2,
                      reason=WasteReason.SPOILAGE, logged_by="gm@example.test",
                      event_date=date(2026, 10, 5))

    assert float(event.quantity) == pytest.approx(2)
    assert float(event.unit_cost) == pytest.approx(4.50)
    assert float(event.cost_value) == pytest.approx(9.00)

    movement = _waste_movement(db, event.id)
    assert movement.movement_type == MovementType.WASTE
    assert float(movement.quantity) == pytest.approx(-2)
    assert movement.location_id == site.id
    assert movement.item_id == steak.id
    assert get_theoretical_stock(db, site.id, steak.id) == pytest.approx(8)

    # Later price changes must not restate the logged waste.
    steak.unit_cost = 6.00
    db.commit()
    db.refresh(event)
    assert float(event.unit_cost) == pytest.approx(4.50)
    assert float(event.cost_value) == pytest.approx(9.00)


def test_waste_for_item_without_cost_has_zero_value(db, world):
    site, salt = world["site_a"], world["salt"]
    _opening(db, site, salt, 3)

    event = log_waste(db, org_unit_id=site.id, item_id=salt.id, quantity=1,
                      reason=WasteReason.OTHER, event_date=date(2026, 10, 5))

    assert event.unit_cost is None
    assert float(event.cost_value) == 0.0


def test_waste_rejects_non_positive_quantity(db, world):
    with pytest.raises(ValueError):
        log_waste(db, org_unit_id=world["site_a"].id, item_id=world["steak"].id,
                  quantity=0, reason=WasteReason.SPOILAGE)


def test_waste_summary_totals_by_reason_and_item_and_aggregates_area(db, world):
    a, b, steak, wine = world["site_a"], world["site_b"], world["steak"], world["wine"]
    log_waste(db, org_unit_id=a.id, item_id=steak.id, quantity=2,
              reason=WasteReason.SPOILAGE, event_date=date(2026, 10, 5))   # 9.00
    log_waste(db, org_unit_id=b.id, item_id=steak.id, quantity=1,
              reason=WasteReason.EXPIRED, event_date=date(2026, 10, 6))    # 4.50
    log_waste(db, org_unit_id=b.id, item_id=wine.id, quantity=0.5,
              reason=WasteReason.SPOILAGE, event_date=date(2026, 10, 7))   # 6.00
    log_waste(db, org_unit_id=a.id, item_id=wine.id, quantity=1,
              reason=WasteReason.STAFF_MEAL, event_date=date(2026, 9, 30))  # outside window

    area = waste_summary(db, world["area"].id, date(2026, 10, 1), date(2026, 10, 31))
    assert area["events"] == 3
    assert float(area["total_cost_value"]) == pytest.approx(19.50)

    by_reason = {r["reason"]: r for r in area["by_reason"]}
    assert float(by_reason["spoilage"]["cost_value"]) == pytest.approx(15.00)
    assert by_reason["spoilage"]["events"] == 2
    assert float(by_reason["expired"]["cost_value"]) == pytest.approx(4.50)
    assert "staff_meal" not in by_reason

    by_item = {i["item_id"]: i for i in area["by_item"]}
    assert float(by_item[steak.id]["quantity"]) == pytest.approx(3)
    assert float(by_item[steak.id]["cost_value"]) == pytest.approx(13.50)
    assert float(by_item[wine.id]["cost_value"]) == pytest.approx(6.00)
    # Sorted by cost descending.
    assert [i["item_id"] for i in area["by_item"]] == [steak.id, wine.id]

    site_a_only = waste_summary(db, a.id, date(2026, 10, 1), date(2026, 10, 31))
    assert site_a_only["events"] == 1
    assert float(site_a_only["total_cost_value"]) == pytest.approx(9.00)


# ── Stock counts ───────────────────────────────────────────────────────────────

def test_count_creation_snapshots_system_qty_from_template(db, world):
    site, steak, wine, salt = world["site_a"], world["steak"], world["wine"], world["salt"]
    _opening(db, site, steak, 10)
    template = create_template(db, name="Walk-in", item_ids=[salt.id, steak.id, wine.id, steak.id],
                               org_unit_id=site.id)

    count = create_count(db, org_unit_id=site.id, name="Monday count",
                         count_date=date(2026, 10, 12), template_id=template.id)

    lines = {line.item_id: line for line in count.lines}
    # Template order preserved, duplicates removed.
    assert [line.item_id for line in count.lines] == [salt.id, steak.id, wine.id]
    assert float(lines[steak.id].system_qty) == pytest.approx(10)
    assert float(lines[wine.id].system_qty) == pytest.approx(0)
    assert count.status == StockCountStatus.OPEN

    # The snapshot stays fixed when stock moves after the count was opened.
    _opening(db, site, steak, 5)
    db.refresh(count)
    assert float(next(l for l in count.lines if l.item_id == steak.id).system_qty) == pytest.approx(10)
    assert get_theoretical_stock(db, site.id, steak.id) == pytest.approx(15)


def test_count_rejects_area_level_unit_and_bad_arguments(db, world):
    with pytest.raises(ValueError):
        create_count(db, org_unit_id=world["area"].id, name="x",
                     count_date=date(2026, 10, 12), item_ids=[world["steak"].id])
    with pytest.raises(ValueError):
        create_count(db, org_unit_id=world["site_a"].id, name="x", count_date=date(2026, 10, 12))
    with pytest.raises(ValueError):
        create_count(db, org_unit_id=world["site_a"].id, name="x", count_date=date(2026, 10, 12),
                     template_id=1, item_ids=[world["steak"].id])


def test_submit_refuses_while_a_line_is_uncounted(db, world):
    site, steak, wine = world["site_a"], world["steak"], world["wine"]
    _opening(db, site, steak, 10)
    count = create_count(db, org_unit_id=site.id, name="Partial",
                         count_date=date(2026, 10, 12), item_ids=[steak.id, wine.id])
    record_counts(db, count.id, [{"item_id": steak.id, "counted_qty": 9}])

    with pytest.raises(ValueError, match=rf"items: \[{wine.id}\]"):
        submit_count(db, count.id)

    db.refresh(count)
    assert count.status == StockCountStatus.OPEN
    assert count.submitted_at is None
    assert db.query(StockMovement).filter(StockMovement.reference_type == "stock_count").count() == 0


def test_submit_posts_adjustments_so_on_hand_equals_counted(db, world):
    site, steak, wine, salt = world["site_a"], world["steak"], world["wine"], world["salt"]
    _opening(db, site, steak, 10)
    count = create_count(db, org_unit_id=site.id, name="Full",
                         count_date=date(2026, 10, 12), item_ids=[steak.id, wine.id, salt.id])
    record_counts(db, count.id, [
        {"item_id": steak.id, "counted_qty": 7, "counted_by": "manager"},
        {"item_id": wine.id, "counted_qty": 2},
        {"item_id": salt.id, "counted_qty": 0},
    ])

    submit_count(db, count.id)

    assert get_theoretical_stock(db, site.id, steak.id) == pytest.approx(7)
    assert get_theoretical_stock(db, site.id, wine.id) == pytest.approx(2)
    assert get_theoretical_stock(db, site.id, salt.id) == pytest.approx(0)

    adjustments = db.execute(
        select(StockMovement).where(StockMovement.reference_type == "stock_count",
                                    StockMovement.reference_id == count.id)
    ).scalars().all()
    # One adjustment per non-zero variance: steak and wine, not salt.
    assert len(adjustments) == 2
    assert all(a.movement_type == MovementType.ADJUSTMENT for a in adjustments)

    lines = {line.item_id: line for line in count.lines}
    assert float(lines[steak.id].variance_qty) == pytest.approx(-3)
    assert float(lines[steak.id].variance_value) == pytest.approx(-13.50)
    assert float(lines[wine.id].variance_value) == pytest.approx(24.00)
    assert float(lines[salt.id].variance_value) == pytest.approx(0)
    assert count.status == StockCountStatus.SUBMITTED
    assert count.submitted_at is not None

    with pytest.raises(ValueError):
        submit_count(db, count.id)


def test_submit_adjusts_to_counted_even_if_stock_moved_after_count_opened(db, world):
    site, steak = world["site_a"], world["steak"]
    _opening(db, site, steak, 10)
    count = create_count(db, org_unit_id=site.id, name="Moved",
                         count_date=date(2026, 10, 12), item_ids=[steak.id])
    _opening(db, site, steak, 5)  # a delivery lands after the count was opened
    record_counts(db, count.id, [{"item_id": steak.id, "counted_qty": 12}])

    submit_count(db, count.id)

    assert get_theoretical_stock(db, site.id, steak.id) == pytest.approx(12)


def _record_and_submit(db, unit, name, day, lines):
    count = create_count(db, org_unit_id=unit.id, name=name, count_date=day,
                         item_ids=[item.id for item, _ in lines])
    record_counts(db, count.id, [{"item_id": item.id, "counted_qty": qty} for item, qty in lines])
    return submit_count(db, count.id)


def test_variance_summary_sign_value_and_top_items(db, world):
    site, steak, wine = world["site_a"], world["steak"], world["wine"]
    _opening(db, site, steak, 10)
    _opening(db, site, wine, 5)

    # Count 1: steak 10 -> 7 (-3 x 4.50 = -13.50); wine 5 -> 4 (-1 x 12 = -12.00)
    _record_and_submit(db, site, "Week 1", date(2026, 10, 5), [(steak, 7), (wine, 4)])
    # Count 2: steak 7 -> 8 (+1 x 4.50 = +4.50)
    _record_and_submit(db, site, "Week 2", date(2026, 10, 12), [(steak, 8), (world["salt"], 0)])
    # Open count (not submitted) must not contribute.
    open_count = create_count(db, org_unit_id=site.id, name="Open", count_date=date(2026, 10, 13),
                              item_ids=[steak.id])
    record_counts(db, open_count.id, [{"item_id": steak.id, "counted_qty": 0}])

    summary = count_variance_summary(db, world["area"].id, date(2026, 10, 1), date(2026, 10, 31))

    assert summary["counts"] == 2
    assert float(summary["total_variance_value"]) == pytest.approx(-21.00)  # net shortage
    assert float(period_count_variance(db, world["area"].id, date(2026, 10, 1),
                                       date(2026, 10, 31))) == pytest.approx(-21.00)

    top = summary["top_items"]
    # Ranked by absolute value: wine (-12.00) before steak (-13.50 + 4.50 = -9.00).
    assert [t["item_id"] for t in top] == [wine.id, steak.id]  # salt had zero variance, excluded
    assert float(top[0]["variance_value"]) == pytest.approx(-12.00)
    assert float(top[1]["variance_value"]) == pytest.approx(-9.00)
    assert float(top[1]["variance_qty"]) == pytest.approx(-2)

    # Date window excludes the October counts entirely.
    empty = count_variance_summary(db, world["area"].id, date(2026, 9, 1), date(2026, 9, 30))
    assert empty["counts"] == 0
    assert float(empty["total_variance_value"]) == 0


# ── COS integration ────────────────────────────────────────────────────────────

def test_cos_summary_reports_waste_and_count_variance_terms(db, world):
    site, steak = world["site_a"], world["steak"]
    _opening(db, site, steak, 10)
    log_waste(db, org_unit_id=site.id, item_id=steak.id, quantity=2,
              reason=WasteReason.SPOILAGE, event_date=date(2026, 10, 5))  # 9.00
    # on-hand 10 - 2 wasted = 8; counted 6 -> -2 x 4.50 = -9.00
    _record_and_submit(db, site, "Oct count", date(2026, 10, 20), [(steak, 6)])

    summary = compute_variance(db, site.id, "2026-10")["summary"]

    assert summary["waste_value"] == pytest.approx(9.00)
    assert summary["count_variance_value"] == pytest.approx(-9.00)
    # Existing keys are still present and unchanged in meaning.
    assert "actual_usage_value" in summary and "theoretical_usage_value" in summary
    assert "variance_pct" in summary
