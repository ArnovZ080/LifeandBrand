"""Shopping list per site and one-click draft requisitions (shopping list feature).

Nothing here submits a requisition. create-drafts makes DRAFT requisitions only;
they go through the normal approval flow. Scope follows the par-level routes:
out-of-subtree org units get 403, and non-site units get 400.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_accessible_org_unit_ids, get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.approval_service import ConflictError
from app.services.par_service import ShoppingList, create_draft_requisitions, shopping_list

router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])


class ShoppingLineOut(BaseModel):
    item_id: int
    item_name: str
    unit: str
    on_hand_qty: float
    par_qty: float
    reorder_point: float
    order_qty: float
    estimated_unit_price: float | None
    estimated_value: float | None


class SupplierGroupOut(BaseModel):
    supplier_id: int
    supplier_name: str
    lines: list[ShoppingLineOut]
    total_estimated_value: float


class ShoppingListOut(BaseModel):
    org_unit_id: int
    generated_at: datetime
    groups: list[SupplierGroupOut]
    unassigned: list[ShoppingLineOut]

    @classmethod
    def from_list(cls, sl: ShoppingList) -> "ShoppingListOut":
        def line(l) -> ShoppingLineOut:
            return ShoppingLineOut(
                item_id=l.item_id, item_name=l.item_name, unit=l.unit,
                on_hand_qty=float(l.on_hand_qty), par_qty=float(l.par_qty),
                reorder_point=float(l.reorder_point), order_qty=float(l.order_qty),
                estimated_unit_price=float(l.estimated_unit_price) if l.estimated_unit_price is not None else None,
                estimated_value=float(l.estimated_value) if l.estimated_value is not None else None,
            )
        return cls(
            org_unit_id=sl.org_unit_id, generated_at=sl.generated_at,
            groups=[
                SupplierGroupOut(
                    supplier_id=g.supplier_id, supplier_name=g.supplier_name,
                    lines=[line(l) for l in g.lines],
                    total_estimated_value=float(g.total_estimated_value),
                )
                for g in sl.groups
            ],
            unassigned=[line(l) for l in sl.unassigned],
        )


class CreateDraftsIn(BaseModel):
    org_unit_id: int


class DraftOut(BaseModel):
    id: int
    requisition_number: str
    supplier_id: int | None
    status: str
    line_count: int


class DraftsOut(BaseModel):
    requisitions: list[DraftOut]


def _call(fn, *args, **kwargs):
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


@router.get("/", response_model=ShoppingListOut)
def get_shopping_list(
    org_unit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=org_unit_id, current_user=current_user, db=db)
    return ShoppingListOut.from_list(_call(shopping_list, db, org_unit_id))


@router.post("/create-drafts", response_model=DraftsOut, status_code=201)
def create_drafts(
    body: CreateDraftsIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_accessible_org_unit_ids(requested_org_unit_id=body.org_unit_id, current_user=current_user, db=db)
    requisitions = _call(create_draft_requisitions, db, body.org_unit_id, current_user)
    return DraftsOut(requisitions=[
        DraftOut(
            id=r.id, requisition_number=r.requisition_number, supplier_id=r.supplier_id,
            status=r.status.value, line_count=len(r.lines),
        )
        for r in requisitions
    ])
