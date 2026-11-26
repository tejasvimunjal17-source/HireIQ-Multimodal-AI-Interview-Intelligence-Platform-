"""Structure of `evaluations.nlp_enrichment` (Day 5). Validated before it is stored.

Everything here is CONTEXT for a human reviewer. Nothing in this structure is used to compute the score or the
recommendation, and the confidence block says so explicitly (`affects_evaluation` is always False).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1
Entry = Annotated[str, Field(min_length=1, max_length=100)]
ENTITY_LABELS = (
    "ORG", "PERSON", "GPE", "LOC", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE", "DATE", "TECHNOLOGY",
)
# NORP (nationalities, religious and political groups) is deliberately NOT kept: it describes protected groups.


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Keyword(_Strict):
    text: Entry
    count: int = Field(ge=1, le=10_000)


class Entity(_Strict):
    text: Entry
    label: Literal[ENTITY_LABELS]  # type: ignore[valid-type]
    count: int = Field(ge=1, le=10_000)


class Sentiment(_Strict):
    positive: float = Field(ge=0, le=1)
    negative: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)
    compound: float = Field(ge=-1, le=1)
    label: Literal["positive", "neutral", "negative"]
    note: str = "Tone of the wording only. Not a measure of competence, confidence or honesty."


class ConfidenceIndicator(_Strict):
    name: Entry
    value: float = Field(ge=0, le=1)
    weight: float = Field(gt=0, le=1)
    limitation: str = Field(min_length=1, max_length=400)


class Confidence(_Strict):
    kind: Literal["heuristic"] = "heuristic"
    score: float = Field(ge=0, le=1)
    label: Literal["low", "moderate", "high"]
    indicators: tuple[ConfidenceIndicator, ...] = Field(max_length=10)
    unavailable: tuple[str, ...] = ()
    affects_evaluation: Literal[False] = False
    disclaimer: str = (
        "Experimental text-pattern heuristic. Not a validated measure of a person's confidence, personality, "
        "honesty, intelligence or competence, and it never influences the score or the recommendation."
    )


class NlpEnrichment(_Strict):
    schema_version: Literal[1] = 1
    status: Literal["completed", "partial", "failed", "skipped"]
    word_count: int = Field(ge=0, le=100_000)
    keywords: tuple[Keyword, ...] | None = Field(default=None, max_length=20)
    entities: tuple[Entity, ...] | None = Field(default=None, max_length=30)
    sentiment: Sentiment | None = None
    confidence: Confidence | None = None
    errors: dict[str, str] = Field(default_factory=dict)  # component -> short machine code; never text
    models: dict[str, str] = Field(default_factory=dict)  # e.g. {"spacy": "en_core_web_sm 3.8.0"}
