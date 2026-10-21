"""
Wastage logging (Feature 1).

A WasteEvent records stock thrown away or written off at an org unit. Each
event also posts a negative StockMovement (movement_type WASTE) so on-hand
stock falls immediately. unit_cost is snapshotted at logging time, so later
changes to Item.unit_cost do not rewrite the historical cost of waste.
"""
from datetime import datetime, date
import enum
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class WasteReason(str, enum.Enum):
    SPOILAGE = "spoilage"
    OVERPRODUCTION = "overproduction"
    PREP_ERROR = "prep_error"
    EXPIRED = "expired"
    STAFF_MEAL = "staff_meal"
    CUSTOMER_RETURN = "customer_return"
    OTHER = "other"


def _enum_values(enum_cls):
    # Store the lowercase values (not the member names) so the column matches
    # the labels created in migration 0005.
    return [member.value for member in enum_cls]


class WasteEvent(Base):
    __tablename__ = "waste_events"
    __table_args__ = (Index("ix_waste_events_unit_date", "org_unit_id", "event_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)  # always positive
    reason: Mapped[WasteReason] = mapped_column(
        Enum(WasteReason, name="wastereason", values_callable=_enum_values), nullable=False
    )
    reason_note: Mapped[str] = mapped_column(Text, nullable=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)  # snapshot at logging
    cost_value: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    logged_by: Mapped[str] = mapped_column(String(100), nullable=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org_unit: Mapped["OrgUnit"] = relationship()
    item: Mapped["Item"] = relationship()
