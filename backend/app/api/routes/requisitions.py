"""Requisitions, approval decisions and conversion to purchase orders (Feature 2).

Scope: reads return 404 for records outside the caller's org subtree; writes and
decisions return 403 so the caller learns the action is not allowed.
"""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_accessible_org_unit_ids, get_current_user, get_subtree_ids
from app.db.database import get_db
from app.models.approval import ApprovalRequest, ApprovalStatus, ApprovalSubject, DecisionOutcome
from app.models.requisition import Requisition, RequisitionStatus
from app.models.user import User
from app.services import approval_service
from app.services.approval_service import ConflictError
from app.services.requisition_service import (
    LineSpec, convert, create_draft, submit, update_draft,
)

router = APIRouter(prefix="/requisitions", tags=["requisitions"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class LineIn(BaseModel):
    item_id: int
    quantity: float = Field(gt=0)
    notes: str | None = None


class RequisitionCreate(BaseModel):
    org_unit_id: int
    supplier_id: int | None = None
    needed_by: date | None = None
    notes: str | None = None
    requested_by: str | None = Field(default=None, max_length=100)  # defaults to the caller's name
    lines: list[LineIn] = Field(min_length=1)


class RequisitionUpdate(BaseModel):
    supplier_id: int | None = None
    needed_by: date | None = None
    notes: str | None = None
    lines: list[LineIn] = Field(min_length=1)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str | None = None


class RequisitionLineOut(BaseModel):
    id: int
    item_id: int
    quantity: float
    unit_price: float | None
    notes: str | None


class RequisitionOut(BaseModel):
    id: int
    requisition_number: str
    org_unit_id: int
    supplier_id: int | None
    status: RequisitionStatus
    needed_by: date | None
    notes: str | None
    requested_by: str
    total_value: float | None
    created_at: datetime
    submitted_at: datetime | None
    lines: list[RequisitionLineOut]

    @classmethod
    def from_req(cls, r: Requisition) -> "RequisitionOut":
        return cls(
            id=r.id,
            requisition_number=r.requisition_number,
            org_unit_id=r.org_unit_id,
            supplier_id=r.supplier_id,
            status=r.status,
            needed_by=r.needed_by,
            notes=r.notes,
            requested_by=r.requested_by,
            total_value=float(r.total_value) if r.total_value is not None else None,
            created_at=r.created_at,
            submitted_at=r.submitted_at,
            lines=[
                RequisitionLineOut(
                    id=line.id,
                    item_id=line.item_id,
                    quantity=float(line.quantity),
                    unit_price=float(line.unit_price) if line.unit_price is not None else None,
                    notes=line.notes,
                )
                for line in r.lines
            ],
        )


class ApprovalDecisionOut(BaseModel):
    id: int
    level: int
    approver_name: str
    approver_role: str
    decision: DecisionOutcome
    comment: str | None
    decided_at: datetime


class ApprovalOut(BaseModel):
    id: int
    subject: ApprovalSubject
    subject_id: int
    org_unit_id: int
    rule_id: int | None
    levels: list[str]
    current_level: int
    status: ApprovalStatus
    created_at: datetime
    closed_at: datetime | None
    decisions: list[ApprovalDecisionOut]

    @classmethod
    def from_request(cls, a: ApprovalRequest) -> "ApprovalOut":
        return cls(
            id=a.id,
            subject=a.subject,
            subject_id=a.subject_id,
            org_unit_id=a.org_unit_id,
            rule_id=a.rule_id,
            levels=list(a.levels),
            current_level=a.current_level,
            status=a.status,
            created_at=a.created_at,
            closed_at=a.closed_at,
            decisions=[
                ApprovalDecisionOut(
                    id=d.id, level=d.level, approver_name=d.approver_name,
                    approver_role=d.approver_role, decision=d.decision,
                    comment=d.comment, decided_at=d.decided_at,
                )
                for d in a.decisions
            ],
        )


class PurchaseOrderSummaryOut(BaseModel):
    id: int
    po_number: str
    supplier_id: int
    location_id: int
    status: str
    order_date: date
    line_count: int
    awaiting_approval: bool


class ConvertOut(BaseModel):
    requisition: RequisitionOut
    purchase_orders: list[PurchaseOrderSummaryOut]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _call(fn, *args, **kwargs):
    """Run a service call and map its exceptions to HTTP status codes."""
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ConflictError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _lines(body_lines: list[LineIn]) -> list[LineSpec]:
    return [LineSpec(item_id=l.item_id, quantity=l.quantity, notes=l.notes) for l in body_lines]


def _get_or_404(db: Session, requisition_id: int, user: User) -> Requisition:
    """Requisition in the caller's org subtree, otherwise 404."""
    requisition = db.get(Requisition, requisition_id)
    if requisition is None or requisition.org_unit_id not in get_subtree_ids(db, user.org_unit_id):
        raise HTTPException(404, "Requisition not found")
    return requisition


def _get_for_write(db: Session, requisition_id: int, user: User) -> Requisition:
    """Requisition that exists (404), and the caller must cover its unit (403)."""
    requisition = db.get(Requisition, requisition_id)
    if requisition is None:
        raise HTTPException(404, "Requisition not found")
    if requisition.org_unit_id not in get_subtree_ids(db, user.org_unit_id):
        raise HTTPException(403, "Access to this org unit is not allowed")
    return requisition


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=RequisitionOut, status_code=201)
def create_requisition(
    body: RequisitionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.org_unit_id not in get_subtree_ids(db, current_user.org_unit_id):
        raise HTTPException(403, "Access to this org unit is not allowed")
    requisition = _call(
        create_draft, db,
        org_unit_id=body.org_unit_id,
        lines=_lines(body.lines),
        supplier_id=body.supplier_id,
        needed_by=body.needed_by,
        notes=body.notes,
        requested_by=body.requested_by or current_user.name,
        actor=current_user,
    )
    return RequisitionOut.from_req(requisition)


@router.get("/", response_model=list[RequisitionOut])
def list_requisitions(
    org_unit_id: int | None = None,
    status: RequisitionStatus | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unit_ids = get_accessible_org_unit_ids(
        requested_org_unit_id=org_unit_id, current_user=current_user, db=db,
    )
    query = db.query(Requisition).filter(Requisition.org_unit_id.in_(unit_ids))
    if status is not None:
        query = query.filter(Requisition.status == status)
    return [RequisitionOut.from_req(r) for r in query.order_by(Requisition.id.desc()).all()]


@router.get("/{requisition_id}", response_model=RequisitionOut)
def get_requisition(
    requisition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return RequisitionOut.from_req(_get_or_404(db, requisition_id, current_user))


@router.put("/{requisition_id}", response_model=RequisitionOut)
def update_requisition(
    requisition_id: int,
    body: RequisitionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requisition = _get_for_write(db, requisition_id, current_user)
    updated = _call(
        update_draft, db, requisition, _lines(body.lines),
        supplier_id=body.supplier_id, needed_by=body.needed_by, notes=body.notes,
        actor=current_user,
    )
    return RequisitionOut.from_req(updated)


@router.post("/{requisition_id}/submit", response_model=RequisitionOut)
def submit_requisition(
    requisition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requisition = _get_for_write(db, requisition_id, current_user)
    return RequisitionOut.from_req(_call(submit, db, requisition, actor=current_user))


@router.post("/{requisition_id}/convert", response_model=ConvertOut)
def convert_requisition(
    requisition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requisition = _get_for_write(db, requisition_id, current_user)
    purchase_orders = _call(convert, db, requisition, actor=current_user)
    awaiting = {
        po.id: approval_service.get_request(db, ApprovalSubject.PURCHASE_ORDER, po.id) is not None
        for po in purchase_orders
    }
    return ConvertOut(
        requisition=RequisitionOut.from_req(requisition),
        purchase_orders=[
            PurchaseOrderSummaryOut(
                id=po.id,
                po_number=po.po_number,
                supplier_id=po.supplier_id,
                location_id=po.location_id,
                status=po.status.value,
                order_date=po.order_date,
                line_count=len(po.lines),
                awaiting_approval=awaiting[po.id],
            )
            for po in purchase_orders
        ],
    )


@router.post("/{requisition_id}/decisions", response_model=ApprovalOut)
def decide_requisition(
    requisition_id: int,
    body: DecisionIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requisition = db.get(Requisition, requisition_id)
    if requisition is None:
        raise HTTPException(404, "Requisition not found")
    request = approval_service.get_request(db, ApprovalSubject.REQUISITION, requisition_id)
    if request is None:
        raise HTTPException(404, "No approval is open for this requisition")
    outcome = DecisionOutcome.APPROVED if body.decision == "approved" else DecisionOutcome.REJECTED
    _call(approval_service.decide, db, request, current_user, outcome, body.comment)
    db.commit()
    db.refresh(request)
    return ApprovalOut.from_request(request)


@router.get("/{requisition_id}/approvals", response_model=ApprovalOut | None)
def get_requisition_approvals(
    requisition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_or_404(db, requisition_id, current_user)
    request = approval_service.get_request(db, ApprovalSubject.REQUISITION, requisition_id)
    return ApprovalOut.from_request(request) if request is not None else None
