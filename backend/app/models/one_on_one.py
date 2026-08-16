"""
Monthly One-on-One Team Member Meeting record.
Questions match the PDF template exactly (Q1–Q9).
"""

from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class OneOnOneMeeting(Base):
    __tablename__ = "one_on_one_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("org_units.id"), nullable=False)

    # Header
    team_member_name: Mapped[str] = mapped_column(String(150), nullable=False)
    area_manager_name: Mapped[str] = mapped_column(String(150), nullable=False)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Q1–Q9 from the PDF
    q1_experience: Mapped[str] = mapped_column(Text, nullable=True)
    q2_improvements: Mapped[str] = mapped_column(Text, nullable=True)
    q3_concerns: Mapped[str] = mapped_column(Text, nullable=True)
    q4_growth_next_year: Mapped[str] = mapped_column(Text, nullable=True)
    q5_long_term_goals: Mapped[str] = mapped_column(Text, nullable=True)
    q6_mobility: Mapped[str] = mapped_column(Text, nullable=True)
    q7_workplace_issues: Mapped[str] = mapped_column(Text, nullable=True)
    q8_training: Mapped[str] = mapped_column(Text, nullable=True)
    q9_additional_notes: Mapped[str] = mapped_column(Text, nullable=True)

    # Signatures
    team_member_signature: Mapped[str] = mapped_column(String(150), nullable=True)
    am_signature: Mapped[str] = mapped_column(String(150), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    location: Mapped["Location"] = relationship()
