from datetime import datetime
from sqlalchemy import String, DateTime, Numeric, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class MovementType(str, enum.Enum):
    DELIVERY = "delivery"
    SALE = "sale"               # theoretical usage posted from POS
    WASTE = "waste"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    ADJUSTMENT = "adjustment"   # manual correction from a spot check finding
    OPENING = "opening"


class StockMovement(Base):
    """Immutable audit log of every stock movement. Never deleted, only appended."""
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)  # positive = in, negative = out
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    reference_id: Mapped[int] = mapped_column(nullable=True)
    reference_type: Mapped[str] = mapped_column(String(50), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["OrgUnit"] = relationship()
    item: Mapped["Item"] = relationship(back_populates="stock_movements")
