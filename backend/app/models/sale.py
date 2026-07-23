from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Sale(Base):
    """A POS session/batch from Micros. Drives theoretical consumption via recipes."""
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)
    micros_batch_id: Mapped[str] = mapped_column(String(100), nullable=True)
    total_revenue: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["OrgUnit"] = relationship(back_populates="sales")
    lines: Mapped[list["SaleLine"]] = relationship(back_populates="sale", cascade="all, delete-orphan")


class SaleLine(Base):
    """Quantity of a menu item sold. Used with recipes to calculate theoretical usage."""
    __tablename__ = "sale_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    quantity_sold: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    revenue: Mapped[float] = mapped_column(Numeric(12, 4), nullable=True)

    sale: Mapped["Sale"] = relationship(back_populates="lines")
    menu_item: Mapped["MenuItem"] = relationship(back_populates="sale_lines")
