import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Difficulty, QuestionType, enum_column

if TYPE_CHECKING:
    from app.models.candidate_response import CandidateResponse
    from app.models.interview import Interview


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        sa.UniqueConstraint("interview_id", "position", name="uq_questions_interview_id_position"),
    )

    interview_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(enum_column(QuestionType), nullable=False)
    # Which rubric entry (in the YAML file) scores this question. Resolved on Day 4.
    rubric_key: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # --- Day 8 question bank (migration 0004). All optional: existing questions simply have NULL here. ---
    category: Mapped[str | None] = mapped_column(sa.String(50), nullable=True, index=True)  # e.g. "databases"
    difficulty: Mapped[Difficulty | None] = mapped_column(enum_column(Difficulty), nullable=True)
    expected_skills: Mapped[list[str] | None] = mapped_column(sa.JSON, nullable=True)  # e.g. ["sql", "indexing"]

    interview: Mapped["Interview"] = relationship("Interview", back_populates="questions")
    responses: Mapped[list["CandidateResponse"]] = relationship("CandidateResponse", back_populates="question")
