"""Schemas for the candidate-facing interview API (Day 2)."""

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InterviewSummary(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    interview_type: str
    question_count: int
    total_time_limit_seconds: int | None = None


class QuestionPublic(BaseModel):
    """What a candidate may see. Rubric details are deliberately NOT included."""

    id: uuid.UUID
    position: int
    text: str
    question_type: str
    time_limit_seconds: int | None = None


class SessionStartRequest(BaseModel):
    interview_id: uuid.UUID
    candidate_name: str = Field(min_length=1, max_length=200)
    candidate_email: str = Field(max_length=320)
    consent: bool

    @field_validator("candidate_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("candidate_name must not be blank")
        return value

    @field_validator("candidate_email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("candidate_email is not a valid email address")
        return value

    @field_validator("consent")
    @classmethod
    def _consent_required(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("consent must be given to start the interview")
        return value


class SessionView(BaseModel):
    session_id: uuid.UUID
    status: str
    interview: InterviewSummary
    questions: list[QuestionPublic]
    answered_question_ids: list[uuid.UUID]


class ResponseReceipt(BaseModel):
    response_id: uuid.UUID
    question_id: uuid.UUID
    # Always "pending" right after upload: transcription runs asynchronously.
    transcription_status: Literal["pending"]
    size_bytes: int
    content_type: str
    # Day 3: id of the queued Celery task. None if the queue was unavailable (retry endpoint can recover).
    task_id: str | None = None


class SessionCompleteResponse(BaseModel):
    session_id: uuid.UUID
    status: str


# ---------------------------------------------------------------- Day 3: transcription status
class TranscriptionView(BaseModel):
    """What a client may learn about the transcription of ONE answer."""

    response_id: uuid.UUID
    question_id: uuid.UUID
    status: Literal["pending", "processing", "completed", "failed"]
    task_id: str | None = None
    # Only filled when status == "completed".
    transcript: str | None = None
    language: str | None = None
    duration_seconds: float | None = None
    provider: str | None = None
    no_speech_detected: bool = False
    error_code: str | None = None
    error_message: str | None = None
    attempts: int = 0
    can_retry: bool = False
    completed_at: str | None = None
