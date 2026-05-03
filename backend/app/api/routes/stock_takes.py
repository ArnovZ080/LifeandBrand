from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date, datetime
from app.db.database import get_db
from app.models.stock import StockTake, StockTakeLine
from app.services.variance import build_variance_report, ItemVariance

router = APIRouter(prefix="/stock-takes", tags=["stock-takes"])


class StockTakeCreate(BaseModel):
    location_id: int
    take_date: date
    notes: str | None = None
    created_by: str | None = None


class StockTakeLineInput(BaseModel):
    item_id: int
    actual_quantity: float
    unit_cost: float | None = None


class StockTakeOut(BaseModel):
    id: int
    location_id: int
    take_date: date
    is_finalised: bool
    created_by: str | None
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class VarianceOut(BaseModel):
    item_id: int
    item_code: str
    item_name: str
    opening_stock: float
    stock_in: float
    theoretical_usage: float
    theoretical_closing: float
    actual_closing: float
    variance_quantity: float
    unit_cost: float
    variance_value: float


@router.get("/", response_model=list[StockTakeOut])
def list_stock_takes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(StockTake)
    if location_id:
        q = q.filter(StockTake.location_id == location_id)
    return q.order_by(StockTake.take_date.desc()).all()


@router.post("/", response_model=StockTakeOut, status_code=201)
def create_stock_take(payload: StockTakeCreate, db: Session = Depends(get_db)):
    st = StockTake(**payload.model_dump())
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


@router.post("/{stock_take_id}/lines")
def submit_counts(
    stock_take_id: int,
    lines: list[StockTakeLineInput],
    db: Session = Depends(get_db),
):
    st = db.get(StockTake, stock_take_id)
    if not st:
        raise HTTPException(404, "Stock take not found")
    if st.is_finalised:
        raise HTTPException(400, "Stock take is already finalised")

    # Remove existing lines and replace (allows re-submission before finalise)
    db.query(StockTakeLine).filter(StockTakeLine.stock_take_id == stock_take_id).delete()
    for line in lines:
        db.add(StockTakeLine(stock_take_id=stock_take_id, **line.model_dump()))

    db.commit()
    return {"message": f"{len(lines)} lines saved"}


@router.post("/{stock_take_id}/finalise", response_model=list[VarianceOut])
def finalise_stock_take(stock_take_id: int, db: Session = Depends(get_db)):
    st = db.get(StockTake, stock_take_id)
    if not st:
        raise HTTPException(404, "Stock take not found")
    if st.is_finalised:
        raise HTTPException(400, "Already finalised")

    variances = build_variance_report(db, stock_take_id)

    # Persist variance figures back to lines
    line_map = {line.item_id: line for line in st.lines}
    for v in variances:
        if v.item_id in line_map:
            line_map[v.item_id].theoretical_quantity = v.theoretical_closing
            line_map[v.item_id].variance_quantity = v.variance_quantity
            line_map[v.item_id].variance_value = v.variance_value

    st.is_finalised = True
    st.finalised_at = datetime.utcnow()
    db.commit()

    return [VarianceOut(**vars(v)) for v in variances]


@router.get("/{stock_take_id}/variance", response_model=list[VarianceOut])
def get_variance(stock_take_id: int, db: Session = Depends(get_db)):
    st = db.get(StockTake, stock_take_id)
    if not st:
        raise HTTPException(404, "Stock take not found")
    if not st.is_finalised:
        raise HTTPException(400, "Stock take not yet finalised")
    variances = build_variance_report(db, stock_take_id)
    return [VarianceOut(**vars(v)) for v in variances]
