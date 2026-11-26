import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Recommendation, enum_column

if TYPE_CHECKING:
    from app.models.interview_session import InterviewSession


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Final per-session report. The recommendation comes from rubric thresholds (Day 6),
    and the hiring manager keeps the final decision."""

    __tablename__ = "reports"
    __table_args__ = (sa.CheckConstraint("overall_score >= 0 AND overall_score <= 100", name="score_range"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    overall_score: Mapped[float] = mapped_column(sa.Float, nullable=False)
    recommendation: Mapped[Recommendation] = mapped_column(enum_column(Recommendation), nullable=False)
    file_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)

    session: Mapped["InterviewSession"] = relationship("InterviewSession", back_populates="report")
