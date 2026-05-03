from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, ForeignKey, Integer, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class Department(str, enum.Enum):
    BAR = "bar"
    KITCHEN = "kitchen"
    FLOOR = "floor"
    GENERAL = "general"


class UnitOfMeasure(Base):
    __tablename__ = "units_of_measure"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)

    items: Mapped[list["Item"]] = relationship(back_populates="unit_of_measure")


class Item(Base):
    """A stockable ingredient or product."""
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    department: Mapped[Department] = mapped_column(Enum(Department), nullable=False, default=Department.GENERAL)
    unit_of_measure_id: Mapped[int] = mapped_column(ForeignKey("units_of_measure.id"), nullable=False)
    pack_size: Mapped[float] = mapped_column(Numeric(10, 4), default=1)

    # Cost — used for variance value calculations and for prioritising high-value items
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)

    # Perishable / shelf life settings
    is_perishable: Mapped[bool] = mapped_column(Boolean, default=False)
    # Default shelf life in days (e.g. fresh fish = 2, steak = 5).
    # Overridden per batch at receiving if the supplier specifies a different date.
    default_shelf_life_days: Mapped[int] = mapped_column(Integer, nullable=True)

    reorder_level: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    unit_of_measure: Mapped["UnitOfMeasure"] = relationship(back_populates="items")
    supplier_items: Mapped[list["SupplierItem"]] = relationship(back_populates="item")
    recipe_lines: Mapped[list["RecipeLine"]] = relationship(back_populates="item")
    stock_movements: Mapped[list["StockMovement"]] = relationship(back_populates="item")
    spot_check_items: Mapped[list["SpotCheckItem"]] = relationship(back_populates="item")
    batches: Mapped[list["ItemBatch"]] = relationship(back_populates="item")
