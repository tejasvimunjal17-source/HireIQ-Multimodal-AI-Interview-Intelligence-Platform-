"""Schemas of the manager-only question-bank API (Day 8). Pure pydantic: no database imports, so the validation
rules can be tested on their own.

Request models forbid unknown fields (a typo or an attempt to set `is_active` / `id` is an error, not ignored).
Question text and skills are normalised by the validators, so what is stored equals what is validated."""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

QuestionTypeName = Literal["technical", "behavioral"]
DifficultyName = Literal["easy", "medium", "hard"]
InterviewTypeName = Literal["technical", "behavioral", "mixed"]

CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9 +#._/-]{0,59}$")
# Filter input only (never stored): like SKILL_RE but "%" is also accepted so it can be matched literally.
SKILL_FILTER_RE = re.compile(r"^[a-z0-9%][a-z0-9 +#._/%-]{0,59}$")
RUBRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RUBRIC_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]")  # keeps \n and \t

MAX_SKILLS = 10
MIN_TEXT = 10
MAX_TEXT = 2000
MAX_QUESTIONS_PER_INTERVIEW = 50


def normalise_category(value: str) -> str:
    value = value.strip().lower().replace(" ", "-")
    if not CATEGORY_RE.match(value):
        raise ValueError("category must be 1-50 characters: lowercase letters, digits, '-' or '_', starting with a letter")
    return value


def normalise_skill(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().lower())
    if not SKILL_RE.match(value):
        raise ValueError(f"skill '{value[:30]}' is not valid: 1-60 characters (letters, digits, space and + # . _ / -)")
    return value


def normalise_skill_filter(value: str) -> str:
    """Normalise a skill *query* value. The storage validator (normalise_skill) is unchanged and still rejects '%';
    here '%' is allowed because the service escapes it, so it matches only a literal percent sign."""
    value = re.sub(r"\s+", " ", value.strip().lower())
    if not SKILL_FILTER_RE.match(value):
        raise ValueError(f"skill '{value[:30]}' is not valid: 1-60 characters (letters, digits, space and % + # . _ / -)")
    return value


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterviewCreate(_Request):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    interview_type: InterviewTypeName = "mixed"
    rubric_name: str
    total_time_limit_seconds: int | None = Field(default=None, ge=60, le=14400)

    @field_validator("rubric_name")
    @classmethod
    def _rubric_name_shape(cls, value: str) -> str:
        value = value.strip()
        if not RUBRIC_NAME_RE.match(value):
            raise ValueError("rubric_name must be a rubric file name: lowercase letters, digits, '_' or '-' (max 64)")
        return value

    @field_validator("title")
    @classmethod
    def _title_clean(cls, value: str) -> str:
        if _CONTROL.search(value):
            raise ValueError("title contains control characters")
        return value

    @field_validator("description")
    @classmethod
    def _description_clean(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL.search(value):
            raise ValueError("description contains control characters")
        return value or None


class QuestionCreate(_Request):
    text: str
    question_type: QuestionTypeName
    rubric_key: str | None = None  # empty = the question type, exactly like the evaluation pipeline's fallback
    category: str | None = None
    difficulty: DifficultyName | None = None
    expected_skills: list[str] = Field(default_factory=list)
    time_limit_seconds: int | None = Field(default=None, ge=10, le=3600)
    position: int | None = Field(default=None, ge=1, le=200)  # empty = after the last question

    @field_validator("text")
    @classmethod
    def _text_clean(cls, value: str) -> str:
        value = value.strip()
        if _CONTROL.search(value):
            raise ValueError("text contains control characters")
        if not MIN_TEXT <= len(value) <= MAX_TEXT:
            raise ValueError(f"text must be {MIN_TEXT}-{MAX_TEXT} characters long (after trimming)")
        return value

    @field_validator("rubric_key")
    @classmethod
    def _rubric_key_shape(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if not RUBRIC_KEY_RE.match(value):
            raise ValueError("rubric_key must be a rubric block name: lowercase letters, digits or '_', starting with a letter")
        return value

    @field_validator("category")
    @classmethod
    def _category_shape(cls, value: str | None) -> str | None:
        return normalise_category(value) if value and value.strip() else None

    @field_validator("expected_skills")
    @classmethod
    def _skills_clean(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            skill = normalise_skill(raw)
            if skill not in cleaned:
                cleaned.append(skill)
        if len(cleaned) > MAX_SKILLS:
            raise ValueError(f"at most {MAX_SKILLS} distinct expected_skills are allowed")
        return cleaned


class ActivationRequest(_Request):
    active: bool


class QuestionBankItem(BaseModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    interview_title: str
    position: int
    text: str
    question_type: str
    rubric_key: str | None = None
    category: str | None = None
    difficulty: str | None = None
    expected_skills: list[str] = []
    time_limit_seconds: int | None = None


class QuestionBankPage(BaseModel):
    items: list[QuestionBankItem]
    total: int
    page: int
    page_size: int


class InterviewDetail(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    interview_type: str
    rubric_name: str
    total_time_limit_seconds: int | None = None
    is_active: bool
    question_count: int


class RubricCriterionInfo(BaseModel):
    key: str
    name: str
    weight: float


class RubricKeyInfo(BaseModel):
    description: str
    criteria: list[RubricCriterionInfo]


class ScaleInfo(BaseModel):
    min: int
    max: int


class RubricInfo(BaseModel):
    """One rubric file. For an invalid file only `name`, `valid=False` and the problem are given."""

    name: str
    valid: bool
    version: int | None = None
    description: str | None = None
    score_scale: ScaleInfo | None = None
    rubric_keys: dict[str, RubricKeyInfo] = {}
    problem: str | None = None
