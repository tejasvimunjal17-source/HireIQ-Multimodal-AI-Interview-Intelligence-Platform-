"""Response schemas of the hiring-manager dashboard (Day 7). Read-only views of stored data.

Deliberately absent: candidate e-mail, audio paths, task ids and full transcripts (listing and detail views never carry them).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Advice = Literal["proceed", "hold", "reject"]


class AdviceCounts(BaseModel):
    """How many EVALUATED answers of the session carry each stored per-answer advice."""

    proceed: int = 0
    hold: int = 0
    reject: int = 0


class SessionRow(BaseModel):
    session_id: uuid.UUID
    candidate_name: str | None = None
    interview_id: uuid.UUID
    interview_title: str
    interview_date: datetime | None = None
    status: str
    question_count: int
    answered_count: int
    evaluated_count: int
    overall_score: float | None = Field(default=None, description="0-100; null when nothing is scored (never 0 for 'missing')")
    score_source: Literal["stored_report", "average_of_answers"] | None = None
    recommendation: Advice | None = Field(default=None, description="Stored SESSION-level recommendation (reports table); usually null")
    advice: AdviceCounts


class SessionPage(BaseModel):
    items: list[SessionRow]
    total: int
    page: int
    page_size: int


class ScoreBucket(BaseModel):
    label: str
    min: int
    max: int
    count: int


class DashboardSummary(BaseModel):
    total_sessions: int
    by_status: dict[str, int]
    completed_interviews: int = Field(description="Candidate finished: submitted, processing, evaluated or failed")
    awaiting_evaluation: int = Field(description="Finished, evaluation still running: submitted or processing")
    evaluation_failed: int
    evaluated_sessions: int = Field(description="Sessions with status 'evaluated'")
    scored_sessions: int = Field(description="Sessions that have a score (the denominator of average_score)")
    average_score: float | None = Field(default=None, description="Mean of the per-session scores; null when none is scored")
    score_distribution: list[ScoreBucket]


class CriterionView(BaseModel):
    key: str
    score: float
    weight: float | None = None
    explanation: str = ""
    evidence_quotes: list[str] = []


class AnswerView(BaseModel):
    position: int
    question: str
    status_text: str = Field(description="Why the answer has no evaluation; empty when evaluated")
    overall_score: float | None = None
    recommendation: Advice | None = None
    summary: str = ""
    strengths: list[str] = []
    improvements: list[str] = []
    criteria: list[CriterionView] = []
    scale_min: int | None = None
    scale_max: int | None = None
    nlp: dict | None = Field(default=None, description="Experimental, advisory NLP enrichment (validated); never used for the decision")


_NLP_PUBLIC = ("status", "word_count", "keywords", "entities")


def public_nlp(nlp: dict | None) -> dict | None:
    """Only what the dashboard shows. Internal parts of the stored enrichment (error messages, model names, indicator
    internals) are not sent to the browser."""
    if not isinstance(nlp, dict):
        return None
    out = {key: nlp[key] for key in _NLP_PUBLIC if key in nlp}
    sentiment, confidence = nlp.get("sentiment"), nlp.get("confidence")
    if isinstance(sentiment, dict):
        out["sentiment"] = {k: sentiment.get(k) for k in ("label", "positive", "neutral", "negative", "compound")}
    if isinstance(confidence, dict):
        out["confidence"] = {k: confidence.get(k) for k in ("score", "label", "disclaimer")}
    return out


class RadarPointView(BaseModel):
    key: str
    value: float
    answers: int


class CriteriaSummary(BaseModel):
    points: list[RadarPointView] = []
    scale_min: int | None = None
    scale_max: int | None = None
    unavailable_reason: str = ""


class SessionDetail(BaseModel):
    session_id: uuid.UUID
    candidate_name: str | None = None
    interview_title: str | None = None
    interview_date: datetime | None = None
    status: str
    question_count: int
    evaluated_count: int
    is_complete: bool
    overall_score: float | None = None
    score_source: Literal["stored_report", "average_of_answers"] | None = None
    recommendation: Advice | None = None
    answers: list[AnswerView]
    criteria_summary: CriteriaSummary
