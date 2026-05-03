from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class MovementType(str, enum.Enum):
    DELIVERY = "delivery"         # stock in from a delivery
    SALE = "sale"                 # theoretical usage from POS sales
    WASTE = "waste"               # recorded waste/spoilage
    TRANSFER_IN = "transfer_in"   # inter-location transfer in
    TRANSFER_OUT = "transfer_out" # inter-location transfer out
    ADJUSTMENT = "adjustment"     # manual stock adjustment
    OPENING = "opening"           # opening stock entry


class StockMovement(Base):
    """Immutable audit log of every stock movement. Never deleted, only appended."""
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)  # positive = in, negative = out
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    reference_id: Mapped[int] = mapped_column(nullable=True)   # delivery/invoice/sale id
    reference_type: Mapped[str] = mapped_column(String(50), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["Location"] = relationship()
    item: Mapped["Item"] = relationship(back_populates="stock_movements")


class StockTake(Base):
    """A physical stock count session."""
    __tablename__ = "stock_takes"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    take_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_finalised: Mapped[bool] = mapped_column(Boolean, default=False)
    finalised_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["Location"] = relationship(back_populates="stock_takes")
    lines: Mapped[list["StockTakeLine"]] = relationship(back_populates="stock_take", cascade="all, delete-orphan")


class StockTakeLine(Base):
    """Actual counted quantity for one item in a stock take."""
    __tablename__ = "stock_take_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_take_id: Mapped[int] = mapped_column(ForeignKey("stock_takes.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    # Theoretical stock calculated at time of finalisation
    theoretical_quantity: Mapped[float] = mapped_column(Numeric(10, 6), nullable=True)
    actual_quantity: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    # variance = actual - theoretical (negative = lost stock)
    variance_quantity: Mapped[float] = mapped_column(Numeric(10, 6), nullable=True)
    variance_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)

    stock_take: Mapped["StockTake"] = relationship(back_populates="lines")
    item: Mapped["Item"] = relationship(back_populates="stock_take_lines")
