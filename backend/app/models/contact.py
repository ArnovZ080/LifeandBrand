from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base
import enum


class NotificationChannel(str, enum.Enum):
    EMAIL = "email"
    TEAMS = "teams"
    WHATSAPP = "whatsapp"


class LocationContact(Base):
    """
    A manager who receives alerts.
    departments_subscribed is a comma-separated list of departments whose
    alerts this person receives — a Floor manager typically subscribes to
    both 'kitchen' and 'floor' so they can push expiring items at table level.
    """
    __tablename__ = "location_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=True)  # e.g. "Head Chef", "Floor Manager"
    # Contact details — fill in whichever channels are active
    email: Mapped[str] = mapped_column(String(200), nullable=True)
    whatsapp_number: Mapped[str] = mapped_column(String(30), nullable=True)  # E.164 format: +27821234567
    teams_webhook_url: Mapped[str] = mapped_column(String(500), nullable=True)
    # Comma-separated: "email,whatsapp" or "teams"
    active_channels: Mapped[str] = mapped_column(String(100), nullable=False, default="email")
    # Comma-separated dept names: "kitchen,floor" — which alerts this person cares about
    departments_subscribed: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Only send between these hours (local time, 24h format)
    quiet_hours_start: Mapped[int] = mapped_column(nullable=False, default=22)  # 10pm
    quiet_hours_end: Mapped[int] = mapped_column(nullable=False, default=7)     # 7am
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["OrgUnit"] = relationship()
    alerts_sent: Mapped[list["ExpiryAlert"]] = relationship(back_populates="contact")

    def channel_list(self) -> list[NotificationChannel]:
        return [NotificationChannel(c.strip()) for c in self.active_channels.split(",") if c.strip()]

    def department_list(self) -> list[str]:
        return [d.strip() for d in self.departments_subscribed.split(",") if d.strip()]
