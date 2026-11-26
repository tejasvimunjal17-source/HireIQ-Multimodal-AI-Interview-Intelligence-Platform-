from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import InterviewType, enum_column

if TYPE_CHECKING:
    from app.models.interview_session import InterviewSession
    from app.models.question import Question


class Interview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A configurable interview template (a set of questions + a rubric)."""

    __tablename__ = "interviews"

    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    interview_type: Mapped[InterviewType] = mapped_column(
        enum_column(InterviewType), nullable=False, default=InterviewType.MIXED
    )
    # Name of the YAML rubric file (loaded on Day 4). Scoring logic is NOT stored here.
    rubric_name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    total_time_limit_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    questions: Mapped[list["Question"]] = relationship(
        "Question",
        back_populates="interview",
        cascade="all, delete-orphan",
        order_by="Question.position",
    )
    sessions: Mapped[list["InterviewSession"]] = relationship("InterviewSession", back_populates="interview")
