from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, Enum, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
from app.models.contact import NotificationChannel
import enum


class AlertLevel(int, enum.Enum):
    WARNING = 48    # 48 hours before expiry
    ACTION = 24     # 24 hours before expiry
    URGENT = 0      # same day — expires today


class AlertStatus(str, enum.Enum):
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # quiet hours, already sent today, etc.


class ExpiryAlert(Base):
    """
    Record of one alert sent (or attempted) for one batch to one contact.
    Used to deduplicate — one alert per batch per level per contact per day.
    """
    __tablename__ = "expiry_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("item_batches.id"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("location_contacts.id"), nullable=False)
    alert_level: Mapped[int] = mapped_column(Integer, nullable=False)  # hours threshold that triggered
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.SENT)
    message_preview: Mapped[str] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    batch: Mapped["ItemBatch"] = relationship()
    contact: Mapped["LocationContact"] = relationship(back_populates="alerts_sent")
