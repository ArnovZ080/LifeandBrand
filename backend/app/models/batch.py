"""
ItemBatch — tracks a discrete quantity of a perishable item with a specific
best-before date. Created when a delivery is accepted.

Why per-batch tracking matters:
  A kitchen may have three batches of portioned steak active simultaneously:
    - Batch A (received Mon, expires Wed): 4 portions remaining
    - Batch B (received Tue, expires Thu): 12 portions remaining
    - Batch C (received Wed, expires Fri): 20 portions remaining

  A total count of "36 portions on hand" hides the fact that Batch A is
  expiring tonight. Per-batch tracking surfaces this and drives FIFO compliance.
"""

from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, ForeignKey, Integer, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class BatchStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"  # within expiry_warning_days
    EXPIRED = "expired"
    DEPLETED = "depleted"            # quantity_remaining reached zero


EXPIRY_WARNING_DAYS = 2  # flag a batch as expiring_soon within this many days


class ItemBatch(Base):
    __tablename__ = "item_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)

    # Source — nullable so batches can also be created for opening stock manually
    delivery_line_id: Mapped[int] = mapped_column(ForeignKey("delivery_lines.id"), nullable=True)

    # Human-readable reference (e.g. "CK-2024-01-15-001", supplier lot number)
    batch_reference: Mapped[str] = mapped_column(String(100), nullable=True)

    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    best_before_date: Mapped[date] = mapped_column(Date, nullable=True)
    shelf_life_days: Mapped[int] = mapped_column(Integer, nullable=True)

    quantity_received: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    quantity_remaining: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)

    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus), default=BatchStatus.ACTIVE)
    notes: Mapped[str] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    item: Mapped["Item"] = relationship(back_populates="batches")
    location: Mapped["OrgUnit"] = relationship()
    delivery_line: Mapped["DeliveryLine"] = relationship(back_populates="batch")
    spot_check_batch_counts: Mapped[list["SpotCheckBatchCount"]] = relationship(back_populates="batch")

    def refresh_status(self, today: date | None = None) -> None:
        """Recalculate status based on current date and remaining quantity."""
        today = today or date.today()
        if self.quantity_remaining <= 0:
            self.status = BatchStatus.DEPLETED
        elif self.best_before_date and (self.best_before_date - today).days < 0:
            self.status = BatchStatus.EXPIRED
        elif self.best_before_date and (self.best_before_date - today).days <= EXPIRY_WARNING_DAYS:
            self.status = BatchStatus.EXPIRING_SOON
        else:
            self.status = BatchStatus.ACTIVE
