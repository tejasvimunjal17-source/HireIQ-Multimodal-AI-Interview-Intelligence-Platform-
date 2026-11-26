"""YAML rubric configuration (Day 4 foundation): validated models and a safe loader."""

from app.services.rubrics.loader import (
    RubricError,
    RubricFormatError,
    RubricKeyError,
    RubricNotFoundError,
    RubricValidationError,
    load_rubric,
    parse_rubric_text,
    select_for_question,
    select_question_rubric,
)
from app.services.rubrics.models import Criterion, QuestionRubric, Rubric, ScoreRange, ScoreScale

__all__ = [
    "Criterion", "QuestionRubric", "Rubric", "RubricError", "RubricFormatError", "RubricKeyError",
    "RubricNotFoundError", "RubricValidationError", "ScoreRange", "ScoreScale",
    "load_rubric", "parse_rubric_text", "select_for_question", "select_question_rubric",
]
