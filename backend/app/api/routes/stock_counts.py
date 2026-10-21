"""Full stock counts, count templates and count variance endpoints (Feature 1)."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models.stock_count import CountTemplate, StockCount, StockCountLine, StockCountStatus
from app.models.user import User
from app.services.stock_count_service import (
    count_variance_summary, create_count, create_template, record_counts, submit_count,
)

router = APIRouter(prefix="/stock-counts", tags=["stock-counts"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    item_ids: list[int] = Field(min_length=1)
    org_unit_id: int | None = None


class TemplateOut(BaseModel):
    id: int
    name: str
    org_unit_id: int | None
    item_ids: list[int]
    created_at: datetime


class CountCreateIn(BaseModel):
    org_unit_id: int
    name: str = Field(min_length=1, max_length=120)
    count_date: date | None = None
    template_id: int | None = None
    item_ids: list[int] | None = None


class LineCountIn(BaseModel):
    item_id: int
    counted_qty: float = Field(ge=0)
    counted_by: str | None = None
    notes: str | None = None


class LineOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    system_qty: float
    counted_qty: float | None
    variance_qty: float | None
    unit_cost: float | None
    variance_value: float | None
    counted_by: str | None
    counted_at: datetime | None
    notes: str | None


class CountOut(BaseModel):
    id: int
    org_unit_id: int
    template_id: int | None
    name: str
    count_date: date
    status: StockCountStatus
    created_by: str | None
    created_at: datetime
    submitted_at: datetime | None
    lines: list[LineOut]


class ItemVarianceOut(BaseModel):
    item_id: int
    item_name: str
    variance_qty: float
    variance_value: float


class VarianceSummaryOut(BaseModel):
    org_unit_id: int
    date_from: date
    date_to: date
    counts: int
    total_variance_value: float
    top_items: list[ItemVarianceOut]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _template_out(t: CountTemplate) -> TemplateOut:
    return TemplateOut(id=t.id, name=t.name, org_unit_id=t.org_unit_id,
                       item_ids=list(t.item_ids), created_at=t.created_at)


def _line_out(line: StockCountLine) -> LineOut:
    f = lambda v: float(v) if v is not None else None  # noqa: E731
    return LineOut(
        id=line.id,
        item_id=line.item_id,
        item_name=line.item.name if line.item else f"item #{line.item_id}",
        system_qty=float(line.system_qty),
        counted_qty=f(line.counted_qty),
        variance_qty=f(line.variance_qty),
        unit_cost=f(line.unit_cost),
        variance_value=f(line.variance_value),
        counted_by=line.counted_by,
        counted_at=line.counted_at,
        notes=line.notes,
    )


def _count_out(count: StockCount) -> CountOut:
    return CountOut(
        id=count.id,
        org_unit_id=count.org_unit_id,
        template_id=count.template_id,
        name=count.name,
        count_date=count.count_date,
        status=count.status,
        created_by=count.created_by,
        created_at=count.created_at,
        submitted_at=count.submitted_at,
        lines=[_line_out(line) for line in count.lines],
    )


def _map_service_error(exc: Exception):
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc))
    return HTTPException(400, str(exc))


def _load_count(db: Session, count_id: int) -> StockCount:
    count = db.get(StockCount, count_id)
    if count is None:
        raise HTTPException(404, "Stock count not found")
    return count


# ── Templates ──────────────────────────────────────────────────────────────────

@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_count_template(
    payload: TemplateIn,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        template = create_template(db, name=payload.name, item_ids=payload.item_ids,
                                   org_unit_id=payload.org_unit_id)
    except (LookupError, ValueError) as exc:
        raise _map_service_error(exc)
    return _template_out(template)


@router.get("/templates", response_model=list[TemplateOut])
def list_count_templates(
    org_unit_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(CountTemplate)
    if org_unit_id is not None:
        # Site-specific templates for this site, plus all-sites templates (null)
        q = q.filter((CountTemplate.org_unit_id == org_unit_id) | (CountTemplate.org_unit_id.is_(None)))
    return [_template_out(t) for t in q.order_by(CountTemplate.name).all()]


# ── Counts ─────────────────────────────────────────────────────────────────────

@router.post("/", response_model=CountOut, status_code=201)
def open_stock_count(
    payload: CountCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        count = create_count(
            db,
            org_unit_id=payload.org_unit_id,
            name=payload.name,
            count_date=payload.count_date or date.today(),
            template_id=payload.template_id,
            item_ids=payload.item_ids,
            created_by=current_user.email,
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_error(exc)
    return _count_out(count)


# Declared before "/{stock_count_id}" so the literal path is not read as an id.
@router.get("/variance-summary", response_model=VarianceSummaryOut)
def get_count_variance_summary(
    org_unit_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if date_to < date_from:
        raise HTTPException(400, "date_to must be on or after date_from")
    result = count_variance_summary(db, org_unit_id, date_from, date_to)
    f = lambda v: float(v) if isinstance(v, Decimal) else v  # noqa: E731
    return VarianceSummaryOut(
        org_unit_id=org_unit_id,
        date_from=date_from,
        date_to=date_to,
        counts=result["counts"],
        total_variance_value=f(result["total_variance_value"]),
        top_items=[
            ItemVarianceOut(item_id=r["item_id"], item_name=r["item_name"],
                            variance_qty=f(r["variance_qty"]), variance_value=f(r["variance_value"]))
            for r in result["top_items"]
        ],
    )


@router.get("/{stock_count_id}", response_model=CountOut)
def get_stock_count(
    stock_count_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return _count_out(_load_count(db, stock_count_id))


@router.put("/{stock_count_id}/lines", response_model=CountOut)
def record_stock_count_lines(
    stock_count_id: int,
    lines: list[LineCountIn],
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _load_count(db, stock_count_id)
    try:
        count = record_counts(db, stock_count_id, [line.model_dump() for line in lines])
    except (LookupError, ValueError) as exc:
        raise _map_service_error(exc)
    return _count_out(count)


@router.post("/{stock_count_id}/submit", response_model=CountOut)
def submit_stock_count(
    stock_count_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _load_count(db, stock_count_id)
    try:
        count = submit_count(db, stock_count_id)
    except (LookupError, ValueError) as exc:
        raise _map_service_error(exc)
    return _count_out(count)
