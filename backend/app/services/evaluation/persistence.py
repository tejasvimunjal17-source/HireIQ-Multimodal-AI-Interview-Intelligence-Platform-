"""Maps a validated, scored evaluation to the columns of the existing `Evaluation` model (pure).

This is the ONLY place where numbers are rounded (the persistence boundary).

evaluations column      content
overall_score           weighted score converted to 0-100, rounded to 2 decimals (DB check: 0..100)
criteria_scores (JSON)  {criterion_key: {score, weight, weighted_contribution, explanation, evidence_quotes}}
                        in rubric order. weight is the YAML weight; contribution rounded to 4 decimals.
explanation             the model's summary
recommendation          the validated recommendation as its string value (dedicated column, migration 0003)
evaluation_details      {strengths, areas_for_improvement, model_overall_score, weighted_score,
                         score_scale, rubric_key, rubric_version, prompt_version}
nlp_enrichment          left NULL (Day 5)
llm_provider/llm_model/rubric_name  as used
"""

from __future__ import annotations

from typing import Any

from app.schemas.evaluation import EvaluationResponse
from app.services.evaluation.prompt_builder import EvaluationPrompt
from app.services.evaluation.scoring import FLOAT_TOLERANCE, ScoreBreakdown, ScoringError

SCORE_DECIMALS = 2
CONTRIBUTION_DECIMALS = 4


def build_evaluation_fields(
    *,
    parsed: EvaluationResponse,
    breakdown: ScoreBreakdown,
    prompt: EvaluationPrompt,
    provider: str,
    model: str,
) -> dict[str, Any]:
    # The weighted mean of validated scores is mathematically within 0..100 (scoring.calculate_score enforces it).
    # Nothing is clamped here: a value outside the range (beyond float noise) is a bug and is rejected, not hidden.
    raw = breakdown.overall_score_100
    if not (-FLOAT_TOLERANCE <= raw <= 100.0 + FLOAT_TOLERANCE):
        raise ScoringError("The overall score is outside 0-100.")
    overall = round(raw, SCORE_DECIMALS)
    if not 0.0 <= overall <= 100.0:  # rounding float noise (e.g. 100.00000000000001) lands exactly on the bound
        raise ScoringError("The rounded overall score is outside 0-100.")
    return {
        "overall_score": overall,
        "criteria_scores": {
            c.key: {
                "score": c.score,
                "weight": c.weight,
                "weighted_contribution": round(c.weighted_contribution, CONTRIBUTION_DECIMALS),
                "explanation": c.explanation,
                "evidence_quotes": list(c.evidence_quotes),
            }
            for c in breakdown.criteria
        },
        "explanation": parsed.summary,
        "recommendation": parsed.recommendation,  # plain "proceed"|"hold"|"reject"; the engine converts to the DB enum
        "evaluation_details": {
            "strengths": list(parsed.strengths),
            "areas_for_improvement": list(parsed.areas_for_improvement),
            "model_overall_score": parsed.overall_score,
            "weighted_score": round(breakdown.weighted_score, 4),
            "score_scale": {"min": breakdown.score_min, "max": breakdown.score_max},
            "rubric_key": prompt.rubric_key,
            "rubric_version": prompt.rubric_version,
            "prompt_version": prompt.prompt_version,
        },
        "nlp_enrichment": None,
        "llm_provider": provider[:50],
        "llm_model": model[:100],
        "rubric_name": prompt.rubric_name[:100],
    }
