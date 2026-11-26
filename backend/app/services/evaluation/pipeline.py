"""Database-free evaluation pipeline (Day 4, Phase 3): prompt -> provider -> validation -> weighted score.

Imported by engine.py, which adds the database claim/persistence. Kept separate so the whole scoring path
can be exercised without a database.

`evaluate_transcript` is the database-free core:
    load rubric (YAML) -> build prompt -> call provider -> parse + validate (schema, rubric, transcript
    evidence) -> weighted score. It returns a ValidatedEvaluation or raises EvaluationFailure.
Nothing unvalidated leaves this function. `run` (below) adds the database claim and persistence.

EvaluationFailure.code values
  retryable  : provider_timeout, provider_unreachable, rate_limited, provider_error, provider_bad_response,
               invalid_json / invalid_response / evidence_invalid (invalid MODEL OUTPUT: retried at most
               MAX_INVALID_OUTPUT_RETRIES time), task_timeout, persistence_error
  permanent  : provider_not_configured, provider_auth, provider_rejected, provider_refused, quota_exceeded,
               provider_unsupported, rubric_missing, rubric_invalid, rubric_key_unsupported, transcript_missing,
               transcript_too_long, question_invalid, scoring_invalid, question_missing, internal_error
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


from app.schemas.evaluation import EvaluationParseError, EvaluationResponse, parse_evaluation_response
from app.services.evaluation.persistence import build_evaluation_fields
from app.services.evaluation.prompt_builder import (
    EmptyTranscriptError, PromptBuildError, TranscriptTooLongError, build_evaluation_prompt,
)
from app.services.evaluation.providers.base import EvaluationProvider, EvaluationProviderError
from app.services.evaluation.scoring import ScoreBreakdown, ScoringError, calculate_score
from app.services.rubrics import (
    RubricError, RubricKeyError, RubricNotFoundError, load_rubric,
)

logger = logging.getLogger(__name__)

MAX_INVALID_OUTPUT_RETRIES = 1  # the model may simply have formatted badly once; never loop on it
MAX_BACKOFF_SECONDS = 300


class EvaluationFailure(Exception):
    """A controlled failure. Carries a code, never candidate text or model output."""

    def __init__(self, code: str, message: str, *, retryable: bool, retry_after: float | None = None,
                 max_retries: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.max_retries = max_retries  # caps the retries for this kind of failure (None = task default)


@dataclass(frozen=True)
class ValidatedEvaluation:
    fields: dict[str, Any]  # ready for Evaluation(**fields, response_id=...)
    breakdown: ScoreBreakdown
    parsed: EvaluationResponse
    provider: str
    model: str


def backoff_seconds(retries_so_far: int, base: int, retry_after: float | None = None) -> int:
    """base, 2*base, 4*base ... capped at 300s; never shorter than the provider's Retry-After."""
    return int(max(min(base * (2 ** retries_so_far), MAX_BACKOFF_SECONDS), retry_after or 0))


def _classify_parse_error(raw: str, error: EvaluationParseError) -> str:
    try:
        json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        return "invalid_json"
    if any("not found in the transcript" in p or "evidence" in p.lower() for p in error.problems):
        return "evidence_invalid"
    return "invalid_response"


def evaluate_transcript(
    *,
    provider: EvaluationProvider,
    rubrics_dir: Path,
    rubric_name: str,
    question_text: str,
    question_type: Any,
    rubric_key: str | None,
    transcript: str,
) -> ValidatedEvaluation:
    try:
        rubric = load_rubric(rubric_name, rubrics_dir)
    except RubricNotFoundError:
        raise EvaluationFailure("rubric_missing", "The interview's rubric file was not found.", retryable=False) from None
    except RubricError:
        raise EvaluationFailure("rubric_invalid", "The interview's rubric file is invalid.", retryable=False) from None

    try:
        prompt = build_evaluation_prompt(
            rubric=rubric, question_text=question_text, transcript=transcript,
            rubric_key=rubric_key, question_type=question_type,
        )
    except RubricKeyError:
        raise EvaluationFailure("rubric_key_unsupported", "The question's rubric key is not in the rubric.", retryable=False) from None
    except EmptyTranscriptError:
        raise EvaluationFailure("transcript_missing", "There is no transcript to evaluate.", retryable=False) from None
    except TranscriptTooLongError:
        raise EvaluationFailure("transcript_too_long", "The transcript is too long to evaluate.", retryable=False) from None
    except PromptBuildError:
        raise EvaluationFailure("question_invalid", "The question cannot be turned into a prompt.", retryable=False) from None

    try:
        output = provider.evaluate(prompt)
    except EvaluationProviderError as exc:
        raise EvaluationFailure(exc.code, str(exc), retryable=exc.retryable, retry_after=exc.retry_after) from None

    try:
        parsed = parse_evaluation_response(output.raw_text, prompt.context)
    except EvaluationParseError as exc:
        code = _classify_parse_error(output.raw_text, exc)
        # Log the CODE and the number of problems only: the problem texts can mention transcript wording.
        logger.warning("Model output rejected code=%s problems=%d provider=%s", code, len(exc.problems), output.provider)
        raise EvaluationFailure(
            code, "The model output failed validation.", retryable=True, max_retries=MAX_INVALID_OUTPUT_RETRIES
        ) from None

    try:
        breakdown = calculate_score(parsed, rubric.for_key(prompt.rubric_key), rubric.score_scale)
        fields = build_evaluation_fields(
            parsed=parsed, breakdown=breakdown, prompt=prompt, provider=output.provider, model=output.model
        )
    except ScoringError:
        raise EvaluationFailure("scoring_invalid", "The validated response could not be scored.", retryable=False) from None
    return ValidatedEvaluation(fields=fields, breakdown=breakdown, parsed=parsed, provider=output.provider, model=output.model)


