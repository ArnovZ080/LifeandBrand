from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    org_units: Mapped[list["OrgUnit"]] = relationship(back_populates="brand")
