"""Importing this package registers every model on Base.metadata (needed by Alembic)."""

from app.models.base import Base
from app.models.candidate import Candidate
from app.models.candidate_response import CandidateResponse
from app.models.enums import (
    Difficulty, EvaluationStatus, InterviewType, QuestionType, Recommendation, SessionStatus, TranscriptionStatus,
)
from app.models.evaluation import Evaluation
from app.models.interview import Interview
from app.models.interview_session import InterviewSession
from app.models.question import Question
from app.models.report import Report

__all__ = [
    "Base",
    "Candidate",
    "CandidateResponse",
    "Difficulty",
    "Evaluation",
    "EvaluationStatus",
    "Interview",
    "InterviewSession",
    "InterviewType",
    "Question",
    "QuestionType",
    "Recommendation",
    "Report",
    "SessionStatus",
    "TranscriptionStatus",
]
