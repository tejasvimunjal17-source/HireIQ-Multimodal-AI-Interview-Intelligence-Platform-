"""Report data model and sanitising (Day 6). Pure Python: no database, no ReportLab.

The loader (loader.py) hands this module plain values read from the database. Everything here is defensive,
because stored JSON can be missing, malformed or from an older version:
- unusable scores/criteria are dropped (never replaced by invented numbers) and counted in `issues`;
- strings are coerced only if they really are strings;
- nothing is recomputed except the session AVERAGE of stored per-answer scores (clearly labelled in the PDF).
The report never calls a model and never writes to the database.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.schemas.nlp import NlpEnrichment

RECOMMENDATIONS = ("proceed", "hold", "reject")
MAX_QUOTES = 5
MAX_QUOTE_CHARS = 1_000
MAX_LIST_ITEMS = 8
MAX_ITEM_CHARS = 400
MAX_TEXT_CHARS = 5_000


@dataclass(frozen=True)
class CriterionData:
    key: str
    score: float
    weight: float | None
    explanation: str
    evidence_quotes: tuple[str, ...]


@dataclass(frozen=True)
class AnswerData:
    position: int
    question: str
    transcript: str | None = field(default=None, repr=False)  # candidate speech: kept out of repr/logs
    transcription_status: str = "pending"
    no_speech: bool = False
    evaluation_status: str = "pending"
    evaluation_error: str | None = None
    overall_score: float | None = None  # stored 0-100 value, unchanged
    recommendation: str | None = None  # stored per-answer advice: proceed | hold | reject
    summary: str = field(default="", repr=False)
    strengths: tuple[str, ...] = field(default=(), repr=False)
    improvements: tuple[str, ...] = field(default=(), repr=False)
    criteria: tuple[CriterionData, ...] = ()
    scale: tuple[int, int] | None = None  # rubric score scale used for the criterion scores
    nlp: dict | None = field(default=None, repr=False)  # validated NlpEnrichment dump (completed/partial only)
    issues: tuple[str, ...] = ()  # data problems found while reading this answer
    answered: bool = True  # False: the interview has this question but no answer was recorded

    @property
    def is_evaluated(self) -> bool:
        return self.overall_score is not None

    @property
    def status_text(self) -> str:
        """Why an answer has no evaluation (empty for evaluated answers)."""
        if self.is_evaluated:
            return ""
        if not self.answered:
            return "No answer was recorded for this question"
        if self.transcription_status in ("pending", "processing"):
            return "Transcription not finished yet"
        if self.transcription_status == "failed":
            return "Transcription failed"
        if self.no_speech or self.evaluation_error == "no_speech":
            return "No speech was detected in this recording (not scored)"
        if self.evaluation_status == "failed":
            return "Automated evaluation failed"
        return "Evaluation not finished yet"


@dataclass(frozen=True)
class ReportData:
    session_id: str
    session_status: str
    candidate_id: str | None
    candidate_name: str | None = field(default=None, repr=False)
    interview_title: str | None = None
    interview_date: datetime | None = None
    answers: tuple[AnswerData, ...] = ()
    stored_overall_score: float | None = None  # reports.overall_score if a Report row exists
    stored_recommendation: str | None = None  # reports.recommendation if a Report row exists

    @property
    def evaluated(self) -> tuple[AnswerData, ...]:
        return tuple(a for a in self.answers if a.is_evaluated)

    @property
    def is_complete(self) -> bool:
        return bool(self.answers) and all(a.is_evaluated or a.no_speech for a in self.answers)

    @property
    def average_score(self) -> float | None:
        """Plain average of the stored per-answer scores (no question weights exist). None without evaluations."""
        scores = [a.overall_score for a in self.evaluated]
        return math.fsum(scores) / len(scores) if scores else None


# ---------------------------------------------------------------- sanitising helpers
def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _strings(value: Any, *, limit: int = MAX_LIST_ITEMS, size: int = MAX_ITEM_CHARS) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(t for t in (_text(v, size) for v in value[:limit]) if t)


def _scale(details: Any) -> tuple[int, int] | None:
    raw = details.get("score_scale") if isinstance(details, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    low, high = _number(raw.get("min")), _number(raw.get("max"))
    if low is None or high is None or high <= low or low != int(low) or high != int(high):
        return None
    return int(low), int(high)


def _criteria(raw: Any, scale: tuple[int, int] | None, issues: list[str]) -> tuple[CriterionData, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        issues.append("criterion data could not be read")
        return ()
    rows, bad = [], 0
    for key, item in raw.items():
        score = _number(item.get("score")) if isinstance(item, Mapping) else None
        if not isinstance(key, str) or not key.strip() or score is None or (scale and not scale[0] <= score <= scale[1]):
            bad += 1
            continue
        weight = _number(item.get("weight"))
        rows.append(CriterionData(
            key=key.strip()[:100], score=score, weight=weight if weight is not None and 0 < weight <= 1 else None,
            explanation=_text(item.get("explanation")),
            evidence_quotes=_strings(item.get("evidence_quotes"), limit=MAX_QUOTES, size=MAX_QUOTE_CHARS),
        ))
    if bad:
        issues.append(f"{bad} criterion entr{'y' if bad == 1 else 'ies'} could not be read and {'was' if bad == 1 else 'were'} left out")
    return tuple(rows)


def _nlp(raw: Any, issues: list[str]) -> dict | None:
    if raw is None:
        return None
    try:
        parsed = NlpEnrichment.model_validate(raw)
    except Exception:  # noqa: BLE001 - malformed stored JSON must not break the report
        issues.append("NLP data could not be read")
        return None
    return parsed.model_dump(mode="json") if parsed.status in ("completed", "partial") else None


def build_answer(raw: Mapping[str, Any]) -> AnswerData:
    """`raw`: position, question, transcript, transcription_status, no_speech, evaluation_status, evaluation_error and,
    when an Evaluation row exists, evaluation = {overall_score, recommendation, explanation, criteria_scores,
    evaluation_details, nlp_enrichment}."""
    issues: list[str] = []
    evaluation = raw.get("evaluation")
    overall = recommendation = scale = None
    summary, strengths, improvements, criteria, nlp = "", (), (), (), None
    if isinstance(evaluation, Mapping):
        value = _number(evaluation.get("overall_score"))
        if value is not None and 0 <= value <= 100:
            overall = value
        else:
            issues.append("the stored overall score is missing or out of range")
        rec = evaluation.get("recommendation")
        rec = getattr(rec, "value", rec)  # DB enum member or plain string
        recommendation = rec if rec in RECOMMENDATIONS else None
        details = evaluation.get("evaluation_details")
        scale = _scale(details)
        summary = _text(evaluation.get("explanation"))
        if isinstance(details, Mapping):
            strengths = _strings(details.get("strengths"))
            improvements = _strings(details.get("areas_for_improvement"))
        criteria = _criteria(evaluation.get("criteria_scores"), scale, issues)
        nlp = _nlp(evaluation.get("nlp_enrichment"), issues)
    transcript = raw.get("transcript")
    return AnswerData(
        position=int(raw.get("position") or 0),
        question=_text(raw.get("question")) or "(question text unavailable)",
        transcript=transcript if isinstance(transcript, str) else None,
        transcription_status=_text(getattr(raw.get("transcription_status"), "value", raw.get("transcription_status")), 20) or "pending",
        no_speech=bool(raw.get("no_speech")),
        evaluation_status=_text(getattr(raw.get("evaluation_status"), "value", raw.get("evaluation_status")), 20) or "pending",
        evaluation_error=_text(raw.get("evaluation_error"), 100) or None,
        overall_score=overall, recommendation=recommendation if overall is not None else None, summary=summary,
        strengths=strengths, improvements=improvements, criteria=criteria, scale=scale, nlp=nlp, issues=tuple(issues),
        answered=raw.get("answered", True) is not False,
    )


def build_report(
    *, session_id: Any, session_status: Any, candidate_id: Any, candidate_name: Any, interview_title: Any,
    interview_date: datetime | None, answers: Sequence[Mapping[str, Any]],
    stored_overall_score: Any = None, stored_recommendation: Any = None,
) -> ReportData:
    rec = getattr(stored_recommendation, "value", stored_recommendation)
    score = _number(stored_overall_score)
    return ReportData(
        session_id=str(session_id),
        session_status=_text(getattr(session_status, "value", session_status), 20) or "unknown",
        candidate_id=str(candidate_id) if candidate_id is not None else None,
        candidate_name=_text(candidate_name, 200) or None,
        interview_title=_text(interview_title, 200) or None,
        interview_date=interview_date,
        answers=tuple(sorted((build_answer(a) for a in answers), key=lambda a: a.position)),
        stored_overall_score=score if score is not None and 0 <= score <= 100 else None,
        stored_recommendation=rec if rec in RECOMMENDATIONS else None,
    )
