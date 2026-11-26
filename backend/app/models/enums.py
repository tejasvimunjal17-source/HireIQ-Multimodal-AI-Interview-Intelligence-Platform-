"""Enumerations stored as plain strings (no native DB enum => easy migrations)."""

from enum import StrEnum

import sqlalchemy as sa


class InterviewType(StrEnum):
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    MIXED = "mixed"


class QuestionType(StrEnum):
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"


class Difficulty(StrEnum):
    """Question-bank difficulty (Day 8). Optional metadata: it never changes how an answer is scored."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SessionStatus(StrEnum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    EVALUATED = "evaluated"
    FAILED = "failed"


class TranscriptionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationStatus(StrEnum):
    """Per-answer LLM evaluation progress (Day 4). PENDING also means "not dispatched yet"."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # nothing to evaluate (no speech): a system outcome, never a zero score


class Recommendation(StrEnum):
    PROCEED = "proceed"
    HOLD = "hold"
    REJECT = "reject"


ENUM_LENGTH = 20


def enum_column(enum_cls: type[StrEnum]) -> sa.Enum:
    """Store the enum VALUE (e.g. 'in_progress') in a VARCHAR column."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=ENUM_LENGTH,
        values_callable=lambda members: [m.value for m in members],
    )
