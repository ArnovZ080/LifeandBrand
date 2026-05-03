from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.db.database import get_db
from app.models.supplier import Supplier, SupplierItem

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


class SupplierCreate(BaseModel):
    name: str
    code: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    payment_terms_days: int = 30
    sage_supplier_id: str | None = None
    notes: str | None = None


class SupplierOut(BaseModel):
    id: int
    name: str
    code: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    payment_terms_days: int
    sage_supplier_id: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[SupplierOut])
def list_suppliers(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Supplier)
    if active_only:
        q = q.filter(Supplier.is_active == True)
    return q.order_by(Supplier.name).all()


@router.post("/", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    if db.query(Supplier).filter(Supplier.code == payload.code).first():
        raise HTTPException(400, f"Supplier code '{payload.code}' already exists")
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    return supplier


class SupplierItemCreate(BaseModel):
    item_id: int
    supplier_sku: str | None = None
    supplier_item_name: str | None = None
    unit_price: float
    pack_size: float = 1
    is_preferred: bool = False


class SupplierItemOut(BaseModel):
    id: int
    supplier_id: int
    item_id: int
    supplier_sku: str | None
    supplier_item_name: str | None
    unit_price: float
    pack_size: float
    is_preferred: bool

    class Config:
        from_attributes = True


@router.get("/{supplier_id}/items", response_model=list[SupplierItemOut])
def list_supplier_items(supplier_id: int, db: Session = Depends(get_db)):
    return db.query(SupplierItem).filter(SupplierItem.supplier_id == supplier_id).all()


@router.post("/{supplier_id}/items", response_model=SupplierItemOut, status_code=201)
def add_supplier_item(supplier_id: int, payload: SupplierItemCreate, db: Session = Depends(get_db)):
    if not db.get(Supplier, supplier_id):
        raise HTTPException(404, "Supplier not found")
    si = SupplierItem(supplier_id=supplier_id, **payload.model_dump())
    db.add(si)
    db.commit()
    db.refresh(si)
    return si
