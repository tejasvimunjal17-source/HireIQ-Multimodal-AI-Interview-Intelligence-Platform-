"""Pydantic models that validate a YAML rubric file (Day 4).

Design rules
- Nothing about scoring is hardcoded in Python: criteria, weights, examples and score bands all come from YAML.
- Validation is strict and loud. Unknown keys, wrong types, bad weights and gaps in the score bands are
  rejected with a message that says WHERE the problem is. Weights are never silently normalised.
- Models are IMMUTABLE once loaded, all the way down: attributes cannot be reassigned (frozen models),
  lists become tuples, and the question_types dictionary becomes a read-only mapping. Collections are
  copied during validation, so changing the parsed YAML dict afterwards cannot change a loaded rubric.
"""

from __future__ import annotations

import math
import re
from types import MappingProxyType
from typing import Annotated, Any, Mapping, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WrapSerializer,
    field_validator,
    model_validator,
)

WEIGHT_TOLERANCE = 1e-6  # |sum(weights) - 1.0| must not exceed this (floating-point slack only)
MAX_SCALE = 100

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"  # criterion keys and question-type keys (e.g. "technical")
NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"  # rubric names / file stems (also blocks path tricks like "../x")

Key = Annotated[str, StringConstraints(pattern=KEY_PATTERN)]
RubricName = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]


_T = TypeVar("_T")


def _list_to_tuple(value: Any) -> Any:
    # Only a real list (what YAML/JSON produce) is converted. Strings, dicts and anything else are left
    # alone so that strict validation still rejects them ("abc" must not become ("a", "b", "c")).
    return tuple(value) if isinstance(value, list) else value


def _freeze_mapping(value: Mapping[Any, Any]) -> Mapping[Any, Any]:
    return MappingProxyType(dict(value))  # a copy: the caller's dict is never aliased


# A YAML list that is stored as an immutable tuple. Use as FrozenTuple[ItemType].
FrozenTuple = Annotated[tuple[_T, ...], BeforeValidator(_list_to_tuple)]
# A YAML mapping that is stored read-only. The serializer keeps model_dump()/model_dump_json() working.
FrozenMapping = Annotated[
    Mapping[Key, _T],
    AfterValidator(_freeze_mapping),
    WrapSerializer(lambda value, handler: handler(dict(value))),
]


def _text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


ShortText = _text(120)
LongText = _text(1000)
ExampleText = _text(1500)


class _Strict(BaseModel):
    # extra="forbid" turns typos such as "wieght" into errors instead of silently ignoring them.
    # strict=True: a YAML number must stay a number and a string a string ("0.5" is NOT a weight).
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ScoreScale(_Strict):
    """The numeric scale a model must use for every criterion, e.g. 0..10."""

    min: int = Field(ge=0, le=MAX_SCALE)
    max: int = Field(ge=1, le=MAX_SCALE)

    @model_validator(mode="after")
    def _max_above_min(self) -> ScoreScale:
        if self.max <= self.min:
            raise ValueError(f"score_scale.max ({self.max}) must be greater than score_scale.min ({self.min})")
        return self


class ScoreRange(_Strict):
    """One band of a criterion's scale, e.g. 7-8 = "Good": what an answer in that band looks like."""

    min: int = Field(ge=0, le=MAX_SCALE)
    max: int = Field(ge=0, le=MAX_SCALE)
    label: ShortText
    description: LongText

    @model_validator(mode="after")
    def _min_not_above_max(self) -> ScoreRange:
        if self.min > self.max:
            raise ValueError(f"score range '{self.label}' has min ({self.min}) greater than max ({self.max})")
        return self


class Criterion(_Strict):
    key: Key
    name: ShortText
    description: LongText
    weight: float = Field(gt=0, le=1, allow_inf_nan=False)
    strong_examples: FrozenTuple[ExampleText] = Field(min_length=1, max_length=5)
    weak_examples: FrozenTuple[ExampleText] = Field(min_length=1, max_length=5)
    score_ranges: FrozenTuple[ScoreRange] = Field(min_length=2, max_length=20)

    @field_validator("weight", mode="before")
    @classmethod
    def _weight_must_be_a_plain_number(cls, value: Any) -> Any:
        # YAML `weight: 5` (int) is fine, but booleans and quoted strings are mistakes, not weights.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("weight must be a number between 0 and 1 (not text or true/false)")
        return float(value)


class QuestionRubric(_Strict):
    """The criteria used for one kind of question (selected through Question.rubric_key)."""

    description: LongText
    criteria: FrozenTuple[Criterion] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _keys_unique_and_weights_sum_to_one(self) -> QuestionRubric:
        keys = [c.key for c in self.criteria]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"duplicate criterion keys: {', '.join(duplicates)}")
        total = math.fsum(c.weight for c in self.criteria)
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            listing = ", ".join(f"{c.key}={c.weight:g}" for c in self.criteria)
            raise ValueError(
                f"criterion weights must sum to 1.0 (tolerance {WEIGHT_TOLERANCE:g}) but sum to {total:.6g} "
                f"({listing}). Weights are never normalised automatically; fix the YAML."
            )
        return self

    @property
    def weight_total(self) -> float:
        return math.fsum(c.weight for c in self.criteria)

    def criterion(self, key: str) -> Criterion:
        for criterion in self.criteria:
            if criterion.key == key:
                return criterion
        raise KeyError(key)


class Rubric(_Strict):
    """A whole rubric file, e.g. config/rubrics/default.yaml."""

    name: RubricName
    version: int = Field(ge=1)
    description: LongText
    score_scale: ScoreScale
    question_types: FrozenMapping[QuestionRubric] = Field(min_length=1)

    @model_validator(mode="after")
    def _score_ranges_cover_the_scale(self) -> Rubric:
        scale = self.score_scale
        for qkey, question in self.question_types.items():
            for criterion in question.criteria:
                where = f"question_types.{qkey}.criteria[{criterion.key}].score_ranges"
                ranges = sorted(criterion.score_ranges, key=lambda r: (r.min, r.max))
                if ranges[0].min != scale.min:
                    raise ValueError(f"{where}: first range must start at the scale minimum {scale.min}, not {ranges[0].min}")
                if ranges[-1].max != scale.max:
                    raise ValueError(f"{where}: last range must end at the scale maximum {scale.max}, not {ranges[-1].max}")
                for previous, current in zip(ranges, ranges[1:]):
                    if current.min <= previous.max:
                        raise ValueError(
                            f"{where}: ranges '{previous.label}' ({previous.min}-{previous.max}) and "
                            f"'{current.label}' ({current.min}-{current.max}) overlap"
                        )
                    if current.min != previous.max + 1:
                        raise ValueError(
                            f"{where}: gap between '{previous.label}' (ends {previous.max}) and "
                            f"'{current.label}' (starts {current.min}); every score must belong to exactly one range"
                        )
        return self

    @property
    def keys(self) -> list[str]:
        """The rubric_key values this file can serve (e.g. ["technical", "behavioral"])."""
        return sorted(self.question_types)

    def for_key(self, rubric_key: str) -> QuestionRubric:
        """Return the criteria for one Question.rubric_key, or raise KeyError."""
        return self.question_types[rubric_key]

    # The read-only mapping cannot be copied or pickled by the default machinery. A loaded rubric can never
    # change, so sharing it on deepcopy is safe, and pickling rebuilds (and re-validates) it from plain data.
    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Rubric:
        return self

    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild_rubric, (self.model_dump(),))


def _rebuild_rubric(data: dict[str, Any]) -> Rubric:
    return Rubric.model_validate(data)


# Kept at module level so tests and the loader can reference the same compiled patterns.
KEY_RE = re.compile(KEY_PATTERN)
NAME_RE = re.compile(NAME_PATTERN)
