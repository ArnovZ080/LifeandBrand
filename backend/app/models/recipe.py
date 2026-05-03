from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class MenuItem(Base):
    """A product sold on the POS (Micros). Linked to a recipe to drive theoretical usage."""
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    micros_item_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    sale_price: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    recipe_lines: Mapped[list["RecipeLine"]] = relationship(back_populates="menu_item")
    sale_lines: Mapped[list["SaleLine"]] = relationship(back_populates="menu_item")


class RecipeLine(Base):
    """One ingredient in a menu item's recipe. quantity_used drives theoretical consumption."""
    __tablename__ = "recipe_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity_used: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)  # in item's UoM
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    menu_item: Mapped["MenuItem"] = relationship(back_populates="recipe_lines")
    item: Mapped["Item"] = relationship(back_populates="recipe_lines")
