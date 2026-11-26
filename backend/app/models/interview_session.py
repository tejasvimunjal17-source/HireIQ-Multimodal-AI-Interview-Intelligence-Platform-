import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SessionStatus, enum_column

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.candidate_response import CandidateResponse
    from app.models.interview import Interview
    from app.models.report import Report


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One candidate taking one interview. A candidate has at most one session per interview."""

    __tablename__ = "interview_sessions"
    __table_args__ = (
        sa.UniqueConstraint("candidate_id", "interview_id", name="uq_interview_sessions_candidate_id_interview_id"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # RESTRICT: an interview that already has sessions cannot be deleted by accident.
    interview_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("interviews.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SessionStatus] = mapped_column(
        enum_column(SessionStatus), nullable=False, default=SessionStatus.CREATED, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="sessions")
    interview: Mapped["Interview"] = relationship("Interview", back_populates="sessions")
    responses: Mapped[list["CandidateResponse"]] = relationship(
        "CandidateResponse", back_populates="session", cascade="all, delete-orphan"
    )
    report: Mapped[Optional["Report"]] = relationship(
        "Report", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
