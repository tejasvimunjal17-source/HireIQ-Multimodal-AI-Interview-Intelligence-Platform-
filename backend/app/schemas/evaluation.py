"""Structured evaluation response (Day 4, Phase 2). Independent of any LLM provider.

A provider (OpenAI, Gemini, a mock, ...) returns TEXT. This module turns that text into a verified
`EvaluationResponse`, or refuses it. Nothing may be stored in `Evaluation` unless it went through
`parse_evaluation_response`.

Two kinds of rules:
1. Structural (always): required fields, exact types, no extra fields, length limits, controlled
   recommendation values, no duplicate criteria.
2. Contextual (needs the rubric and the candidate transcript, passed as `EvaluationContext`):
   every rubric criterion present exactly once, no unknown criterion, scores inside the rubric scale,
   evidence quotes required and actually found in the transcript.

An `EvaluationResponse` cannot be built WITHOUT a context: validating without one fails, so there is no
way to obtain an unchecked instance through normal validation.

What this module deliberately does NOT do
- It never repairs, rounds, clamps or rescales a value ("do not silently normalise"). A bad response is rejected.
- It never computes a weighted overall score. `overall_score` is the model's own holistic score on the
  rubric scale; deciding how it is combined with the criterion scores belongs to the scoring phase.
- It does not call a model or touch the database.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.services.rubrics.models import KEY_PATTERN, FrozenTuple, QuestionRubric, ScoreScale

# Same values as app.models.enums.Recommendation (kept as a Literal so this module needs no database
# imports; tests/test_evaluation_schema.py fails if the two ever drift apart).
Recommendation = Literal["proceed", "hold", "reject"]
RECOMMENDATION_VALUES = ("proceed", "hold", "reject")

MIN_QUOTE_WORDS = 3  # a 1-2 word "quote" matches almost any transcript, so it proves nothing
MAX_RAW_RESPONSE_CHARS = 100_000
MAX_REPORTED_PROBLEMS = 20


def _text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


CriterionKey = Annotated[str, StringConstraints(pattern=KEY_PATTERN)]
ExplanationText = _text(1500)
QuoteText = _text(600)
ListItemText = _text(300)
SummaryText = _text(2000)


# --------------------------------------------------------------------------- text matching helpers
_PUNCTUATION_MAP = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}
)
_NON_WORD = re.compile(r"[\W_]+")


def word_sequence(text: str) -> str:
    """Lower-case words separated by single spaces; punctuation, quote style and spacing are ignored.

    Used only to COMPARE a quote with the transcript. The words themselves (and their order) must match,
    so a paraphrase, a reordered sentence or an invented sentence still fails.
    """
    folded = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION_MAP).casefold()
    return _NON_WORD.sub(" ", folded).strip()


def quote_is_in_transcript(quote: str, transcript: str, *, min_words: int = MIN_QUOTE_WORDS) -> bool:
    """True if `quote` is a contiguous run of words of the transcript (and long enough to mean something)."""
    return _quote_check(word_sequence(quote), word_sequence(transcript), min_words) == "ok"


def _quote_check(quote_words: str, transcript_words: str, min_words: int) -> Literal["ok", "too_short", "not_found"]:
    needed = min(min_words, len(transcript_words.split()))  # a very short answer can only be quoted in full
    if len(quote_words.split()) < max(needed, 1):
        return "too_short"
    return "ok" if f" {quote_words} " in f" {transcript_words} " else "not_found"


# --------------------------------------------------------------------------- the context
@dataclass(frozen=True)
class EvaluationContext:
    """What a response is checked against: the rubric block for the question and the candidate transcript.

    The transcript is excluded from repr() so that logging a context never prints candidate speech.
    """

    criteria_keys: tuple[str, ...]
    score_min: int
    score_max: int
    transcript: str = field(repr=False)
    transcript_words: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.criteria_keys:
            raise ValueError("The rubric block has no criteria.")
        if len(set(self.criteria_keys)) != len(self.criteria_keys):
            raise ValueError("The rubric block has duplicate criterion keys.")
        if self.score_max <= self.score_min:
            raise ValueError("score_max must be greater than score_min.")
        words = word_sequence(self.transcript) if isinstance(self.transcript, str) else ""
        if not words:
            raise ValueError("The transcript is empty: there is nothing to evaluate or quote.")
        object.__setattr__(self, "transcript_words", words)

    @classmethod
    def from_question_rubric(cls, question_rubric: QuestionRubric, score_scale: ScoreScale, transcript: str) -> EvaluationContext:
        return cls(
            criteria_keys=tuple(c.key for c in question_rubric.criteria),
            score_min=score_scale.min,
            score_max=score_scale.max,
            transcript=transcript,
        )


# --------------------------------------------------------------------------- the response schema
class _Strict(BaseModel):
    # extra="forbid": an unexpected field (e.g. a model-invented "weighted_total") is an error, not ignored.
    # strict=True: "7" is not a score, 7.5 is not an integer, "proceed" must be exactly one of the allowed values.
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CriterionEvaluation(_Strict):
    """The model's judgement of ONE rubric criterion."""

    criterion_key: CriterionKey
    score: int = Field(ge=0, le=100)  # the real limits come from the rubric (checked with the context)
    explanation: ExplanationText
    # Verbatim quotes from the candidate transcript. May be empty ONLY when the score is the scale minimum
    # (nothing in the answer earns credit). The quotes themselves are checked against the transcript.
    evidence_quotes: FrozenTuple[QuoteText] = Field(max_length=5)


class EvaluationResponse(_Strict):
    """The complete structured result for one answer."""

    overall_score: float = Field(ge=0, le=100, allow_inf_nan=False)  # the model's holistic score, on the RUBRIC scale (e.g. 0-10)
    criteria_scores: FrozenTuple[CriterionEvaluation] = Field(min_length=1, max_length=12)
    strengths: FrozenTuple[ListItemText] = Field(max_length=5)
    areas_for_improvement: FrozenTuple[ListItemText] = Field(max_length=5)
    summary: SummaryText
    recommendation: Recommendation

    @field_validator("overall_score", mode="before")
    @classmethod
    def _overall_score_is_a_plain_number(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("overall_score must be a number (not text or true/false)")
        return float(value)

    @model_validator(mode="after")
    def _check_against_rubric_and_transcript(self, info: ValidationInfo) -> EvaluationResponse:
        context = info.context
        if not isinstance(context, EvaluationContext):
            raise ValueError(
                "an EvaluationContext (rubric criteria, score range, transcript) is required; "
                "validate with parse_evaluation_response() or model_validate(..., context=EvaluationContext(...))"
            )
        problems = self.problems_for(context)
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def problems_for(self, context: EvaluationContext) -> list[str]:
        """Every way this response disagrees with the rubric or the transcript (empty list = fully valid)."""
        problems: list[str] = []
        low, high = context.score_min, context.score_max

        seen: set[str] = set()
        for item in self.criteria_scores:
            key = item.criterion_key
            if key in seen:
                problems.append(f"criterion '{key}' appears more than once")
            seen.add(key)
            if key not in context.criteria_keys:
                problems.append(f"unknown criterion '{key}' (allowed: {', '.join(context.criteria_keys)})")
        missing = [k for k in context.criteria_keys if k not in seen]
        if missing:
            problems.append(f"missing required criteria: {', '.join(missing)}")

        if not low <= self.overall_score <= high:
            problems.append(f"overall_score {self.overall_score:g} is outside the rubric range {low}-{high}")

        for item in self.criteria_scores:
            key = item.criterion_key
            if not low <= item.score <= high:
                problems.append(f"criterion '{key}': score {item.score} is outside the rubric range {low}-{high}")
            if not item.evidence_quotes and item.score > low:
                problems.append(
                    f"criterion '{key}': evidence quotes are required for any score above the minimum ({low})"
                )
            for number, quote in enumerate(item.evidence_quotes, start=1):
                verdict = _quote_check(word_sequence(quote), context.transcript_words, MIN_QUOTE_WORDS)
                if verdict == "not_found":
                    problems.append(f"criterion '{key}': evidence quote #{number} was not found in the transcript")
                elif verdict == "too_short":
                    problems.append(
                        f"criterion '{key}': evidence quote #{number} is too short "
                        f"(at least {MIN_QUOTE_WORDS} words are needed)"
                    )
        return problems


# --------------------------------------------------------------------------- the parser
class EvaluationParseError(ValueError):
    """The provider output is not an acceptable evaluation. `problems` lists every reason.

    Messages never contain the transcript or the model's text, only field paths and rule descriptions.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems: tuple[str, ...] = tuple(problems)
        shown = list(problems[:MAX_REPORTED_PROBLEMS])
        if len(problems) > MAX_REPORTED_PROBLEMS:
            shown.append(f"... and {len(problems) - MAX_REPORTED_PROBLEMS} more problem(s)")
        super().__init__(f"Evaluation response is invalid ({len(problems)} problem(s)):\n" + "\n".join(f"  - {p}" for p in shown))


def _problems_from(exc: ValidationError) -> list[str]:
    problems: list[str] = []
    for err in exc.errors(include_input=False, include_url=False, include_context=False):
        where = ".".join(str(part) for part in err["loc"])  # empty for rule violations that span the response
        lines = str(err["msg"]).removeprefix("Value error, ").splitlines() or [""]
        problems.extend(f"{where}: {line}" if where else line for line in lines)
    return problems


def parse_evaluation_response(raw: str | bytes | Mapping[str, Any], context: EvaluationContext) -> EvaluationResponse:
    """Validate provider output. `raw` is the model's JSON text (strictly JSON: no code fences, no prose) or
    an already-decoded mapping. Returns a verified response or raises EvaluationParseError."""
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_RAW_RESPONSE_CHARS:
            raise EvaluationParseError([f"response is longer than {MAX_RAW_RESPONSE_CHARS} characters"])
        if not raw.strip():
            raise EvaluationParseError(["response is empty"])
    elif not isinstance(raw, Mapping):
        raise EvaluationParseError(["response must be JSON text or a JSON object"])
    try:
        if isinstance(raw, Mapping):
            return EvaluationResponse.model_validate(dict(raw), context=context)
        return EvaluationResponse.model_validate_json(raw, context=context)
    except ValidationError as exc:
        raise EvaluationParseError(_problems_from(exc)) from None


def response_json_schema() -> dict[str, Any]:
    """The provider-independent JSON Schema of EvaluationResponse (for prompts / provider structured output)."""
    return EvaluationResponse.model_json_schema()


__all__ = [
    "CriterionEvaluation", "EvaluationContext", "EvaluationParseError", "EvaluationResponse",
    "MIN_QUOTE_WORDS", "RECOMMENDATION_VALUES", "Recommendation",
    "parse_evaluation_response", "quote_is_in_transcript", "response_json_schema", "word_sequence",
]
