import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EvaluationStatus, TranscriptionStatus, enum_column

if TYPE_CHECKING:
    from app.models.evaluation import Evaluation
    from app.models.interview_session import InterviewSession
    from app.models.question import Question


class CandidateResponse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A candidate's answer to one question.

    Audio is NOT stored here (or anywhere permanently): it is deleted after
    transcription. Only the transcript and its status are kept.
    """

    __tablename__ = "candidate_responses"
    __table_args__ = (
        sa.UniqueConstraint("session_id", "question_id", name="uq_candidate_responses_session_id_question_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    transcription_status: Mapped[TranscriptionStatus] = mapped_column(
        enum_column(TranscriptionStatus), nullable=False, default=TranscriptionStatus.PENDING, index=True
    )
    transcript: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Whisper segments with timestamps (filled on Day 3).
    transcript_segments: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    audio_duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    # Short error CLASS/message only. Never put transcript text here.
    # A short machine code such as "audio_corrupt" or "rate_limited". Never transcript text.
    transcription_error: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(sa.String(155), nullable=True)

    # --- Day 3: transcription bookkeeping (no audio is ever stored in the database) ---
    transcript_language: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    transcription_provider: Mapped[str | None] = mapped_column(sa.String(30), nullable=True)
    transcription_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")
    transcription_started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    transcription_completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # True when the recording was silent / contained no recognisable speech (transcript is then empty).
    no_speech_detected: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    # --- Day 4: evaluation bookkeeping (claim + failure code; the validated result lives in `evaluations`) ---
    evaluation_status: Mapped[EvaluationStatus] = mapped_column(
        enum_column(EvaluationStatus), nullable=False, default=EvaluationStatus.PENDING, server_default="pending"
    )
    evaluation_task_id: Mapped[str | None] = mapped_column(sa.String(155), nullable=True)
    evaluation_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0, server_default="0")
    # Short machine code ("rate_limited", "no_speech", ...). Never transcript or model text.
    evaluation_error: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)

    session: Mapped["InterviewSession"] = relationship("InterviewSession", back_populates="responses")
    question: Mapped["Question"] = relationship("Question", back_populates="responses")
    evaluation: Mapped[Optional["Evaluation"]] = relationship(
        "Evaluation", back_populates="response", uselist=False, cascade="all, delete-orphan"
    )
