"""
Requisitions (Feature 2).

A site raises a Requisition listing items it needs. Its lines are priced at
submit time (snapshot), then the requisition goes through the approval engine
(see approval.py). Approved requisitions are converted into one
PurchaseOrder per supplier by requisition_service.convert.

Enums store member NAMES (SQLAlchemy default), and migration 0006 creates the
matching labels.
"""
from datetime import datetime, date
import enum
from typing import Optional
from sqlalchemy import (
    String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Integer, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class RequisitionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class Requisition(Base):
    __tablename__ = "requisitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisition_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    status: Mapped[RequisitionStatus] = mapped_column(
        Enum(RequisitionStatus, name="requisitionstatus"),
        default=RequisitionStatus.DRAFT, nullable=False,
    )
    needed_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    total_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)  # set on submit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    org_unit: Mapped["OrgUnit"] = relationship()
    supplier: Mapped[Optional["Supplier"]] = relationship()
    lines: Mapped[list["RequisitionLine"]] = relationship(
        back_populates="requisition", cascade="all, delete-orphan",
    )


class RequisitionLine(Base):
    __tablename__ = "requisition_lines"
    __table_args__ = (UniqueConstraint("requisition_id", "item_id", name="uq_requisition_lines_req_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    requisition_id: Mapped[int] = mapped_column(ForeignKey("requisitions.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    unit_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)  # snapshot at submit
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    requisition: Mapped["Requisition"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship()
