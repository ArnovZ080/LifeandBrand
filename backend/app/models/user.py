from datetime import datetime
import enum
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class UserRole(str, enum.Enum):
    SITE_GM = "site_gm"
    AREA_MANAGER = "area_manager"
    REGIONAL_MANAGER = "regional_manager"
    NATIONAL_OPS = "national_ops"
    MD = "md"
    CEO = "ceo"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    org_unit_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org_unit: Mapped["OrgUnit"] = relationship()
