from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class UnitOfMeasure(Base):
    __tablename__ = "units_of_measure"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # e.g. "kg", "litre", "each"
    abbreviation: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)

    items: Mapped[list["Item"]] = relationship(back_populates="unit_of_measure")


class Item(Base):
    """A stockable ingredient or product."""
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "Meat", "Beverage", "Dry Goods"
    unit_of_measure_id: Mapped[int] = mapped_column(ForeignKey("units_of_measure.id"), nullable=False)
    pack_size: Mapped[float] = mapped_column(Numeric(10, 4), default=1)  # units per purchase pack
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Reorder threshold — alerts when stock falls below this
    reorder_level: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    unit_of_measure: Mapped["UnitOfMeasure"] = relationship(back_populates="items")
    supplier_items: Mapped[list["SupplierItem"]] = relationship(back_populates="item")
    recipe_lines: Mapped[list["RecipeLine"]] = relationship(back_populates="item")
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="item")
    stock_take_lines: Mapped[list["StockTakeLine"]] = relationship(back_populates="item")
