"""Weighted scoring (Day 4, Phase 3). Pure functions: no database, no model call.

Formula (rubric scale, e.g. 0-10):      weighted = sum(weight_i * score_i) / sum(weight_i)
Database scale (0-100):                 overall   = (weighted - scale_min) / (scale_max - scale_min) * 100

- Weights, criteria and the score range come ONLY from the loaded YAML rubric (nothing is written here).
  Dividing by sum(weight) is exact arithmetic for a weighted mean; the rubric loader already guarantees the
  weights sum to 1, so it changes nothing in practice.
- A score outside the rubric range, a non-integer, a missing or extra criterion is an error. Nothing is
  clamped, rescaled or "fixed": the evaluation is rejected instead (ScoringError).
- All intermediate values are unrounded floats (math.fsum). Rounding happens once, in persistence.py.
- The model's own holistic overall_score is NOT used for the result; it is stored beside it for reference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.schemas.evaluation import EvaluationResponse
from app.services.rubrics.models import QuestionRubric, ScoreScale


FLOAT_TOLERANCE = 1e-9  # floating-point noise only; never used to hide a real out-of-range value


class ScoringError(ValueError):
    """The validated response cannot be scored against the rubric. Messages never contain candidate text."""


@dataclass(frozen=True)
class CriterionScore:
    key: str
    score: int
    weight: float
    weighted_contribution: float  # weight * score, unrounded
    explanation: str
    evidence_quotes: tuple[str, ...]


@dataclass(frozen=True)
class ScoreBreakdown:
    criteria: tuple[CriterionScore, ...]  # in rubric (YAML) order
    weighted_score: float  # rubric scale, unrounded
    overall_score_100: float  # database scale, unrounded
    score_min: int
    score_max: int


def to_percentage(weighted_score: float, score_min: int, score_max: int) -> float:
    """Rubric scale -> 0-100. Linear, so the scale minimum maps to 0 and the maximum to 100."""
    if score_max <= score_min:
        raise ScoringError("Invalid score scale.")
    return (weighted_score - score_min) / (score_max - score_min) * 100.0


def calculate_score(
    response: EvaluationResponse, question_rubric: QuestionRubric, scale: ScoreScale
) -> ScoreBreakdown:
    by_key: dict[str, object] = {}
    for item in response.criteria_scores:
        if item.criterion_key in by_key:
            raise ScoringError(f"Criterion '{item.criterion_key}' appears more than once.")
        by_key[item.criterion_key] = item
    expected = [c.key for c in question_rubric.criteria]
    if set(by_key) != set(expected):
        raise ScoringError("The criteria in the response do not match the rubric.")

    rows: list[CriterionScore] = []
    for criterion in question_rubric.criteria:
        item = by_key[criterion.key]
        score = item.score  # type: ignore[attr-defined]
        if isinstance(score, bool) or not isinstance(score, int):
            raise ScoringError(f"Criterion '{criterion.key}': score is not a whole number.")
        if not scale.min <= score <= scale.max:
            raise ScoringError(f"Criterion '{criterion.key}': score {score} is outside {scale.min}-{scale.max}.")
        rows.append(CriterionScore(
            key=criterion.key,
            score=score,
            weight=criterion.weight,
            weighted_contribution=criterion.weight * score,
            explanation=item.explanation,  # type: ignore[attr-defined]
            evidence_quotes=tuple(item.evidence_quotes),  # type: ignore[attr-defined]
        ))

    total_weight = math.fsum(r.weight for r in rows)
    if total_weight <= 0:
        raise ScoringError("The rubric weights do not add up to a positive number.")
    weighted = math.fsum(r.weighted_contribution for r in rows) / total_weight
    # A weighted mean of in-range scores is in range. Allow only floating-point noise; anything else is a bug.
    if not (scale.min - FLOAT_TOLERANCE <= weighted <= scale.max + FLOAT_TOLERANCE):
        raise ScoringError("The weighted score is outside the rubric scale.")
    return ScoreBreakdown(
        criteria=tuple(rows),
        weighted_score=weighted,
        overall_score_100=to_percentage(weighted, scale.min, scale.max),
        score_min=scale.min,
        score_max=scale.max,
    )
