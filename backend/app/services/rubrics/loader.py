"""Load and validate YAML rubric files (Day 4, foundation phase).

- Files are read with a SAFE YAML loader (no arbitrary Python objects) that also rejects duplicate keys,
  because plain PyYAML silently keeps the last duplicate and that could hide a wrong weight.
- A rubric name comes from the database (Interview.rubric_name), so it is validated against a strict
  pattern before it is used to build a file path (no "../" tricks).
- Error messages never echo file contents (rubrics are configuration, but the habit keeps logs clean).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import ValidationError

from app.services.rubrics.models import NAME_RE, QuestionRubric, Rubric

logger = logging.getLogger(__name__)

MAX_RUBRIC_FILE_BYTES = 256 * 1024
MAX_REPORTED_PROBLEMS = 20
RUBRIC_SUFFIX = ".yaml"


class RubricError(Exception):
    """Base class: every rubric problem is a RubricError with a message meant for an operator."""


class RubricNotFoundError(RubricError):
    """The rubric name is invalid or no YAML file with that name exists."""


class RubricFormatError(RubricError):
    """The file is unreadable, too large, not valid YAML, or not a mapping at the top level."""


class RubricValidationError(RubricError):
    """The YAML parsed, but its content breaks the rubric rules (missing field, bad weights, ...)."""


class RubricKeyError(RubricError):
    """The rubric has no entry for the requested Question.rubric_key."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping which repeats a key."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                is_duplicate = key in seen
            except TypeError:  # unhashable key: let the parent raise its normal error
                break
            if is_duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key!r}", key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def format_validation_errors(name: str, exc: ValidationError) -> str:
    """Turn a pydantic error into short lines such as 'question_types.technical.criteria.0.weight: ...'."""
    lines: list[str] = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "(top level)"
        message = str(err["msg"]).removeprefix("Value error, ")
        lines.append(f"  - {location}: {message}")
    extra = len(lines) - MAX_REPORTED_PROBLEMS
    shown = lines[:MAX_REPORTED_PROBLEMS] + ([f"  ... and {extra} more problem(s)"] if extra > 0 else [])
    return f"Rubric '{name}' is invalid ({len(lines)} problem(s)):\n" + "\n".join(shown)


def parse_rubric_text(text: str, *, source: str = "rubric") -> Rubric:
    """Parse + validate YAML text. Raises RubricFormatError or RubricValidationError."""
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - _UniqueKeyLoader is a SafeLoader
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", None) or "invalid YAML"
        raise RubricFormatError(f"Rubric '{source}' is not valid YAML{where}: {problem}.") from None
    if not isinstance(data, dict):
        raise RubricFormatError(f"Rubric '{source}' must be a YAML mapping (key: value pairs) at the top level.")
    try:
        return Rubric.model_validate(data)
    except ValidationError as exc:
        raise RubricValidationError(format_validation_errors(source, exc)) from None


def load_rubric(name: str, rubrics_dir: Path | str) -> Rubric:
    """Load `<rubrics_dir>/<name>.yaml`. `name` is normally Interview.rubric_name."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise RubricNotFoundError(
            "Rubric name is not valid: use lowercase letters, digits, '_' or '-' (max 64 characters)."
        )
    path = Path(rubrics_dir) / f"{name}{RUBRIC_SUFFIX}"
    if not path.is_file():
        raise RubricNotFoundError(f"Rubric '{name}' was not found: expected the file {path}.")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_RUBRIC_FILE_BYTES + 1)
    except OSError as exc:
        raise RubricFormatError(f"Rubric '{name}' could not be read ({type(exc).__name__}).") from None
    if len(raw) > MAX_RUBRIC_FILE_BYTES:
        raise RubricFormatError(f"Rubric '{name}' is larger than {MAX_RUBRIC_FILE_BYTES // 1024} KiB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RubricFormatError(f"Rubric '{name}' is not valid UTF-8 text.") from None

    rubric = parse_rubric_text(text, source=name)
    if rubric.name != name:
        # Evaluation.rubric_name is stored later; a file whose inner name differs would be mislabelled.
        raise RubricValidationError(
            f"Rubric file '{name}{RUBRIC_SUFFIX}' declares name '{rubric.name}'; the name inside must match the file name."
        )
    return rubric


class _QuestionLike(Protocol):
    rubric_key: str | None
    question_type: Any  # QuestionType (a str enum) - kept loose so this module needs no database imports


def select_question_rubric(rubric: Rubric, rubric_key: str | None, question_type: Any = None) -> QuestionRubric:
    """Pick the criteria for a question.

    Uses Question.rubric_key. If it is empty (the column is nullable) the question type's value
    ("technical" / "behavioral") is used instead, so existing questions keep working.
    Raises RubricKeyError when the rubric has no matching entry; it never guesses another one.
    """
    key = (rubric_key or "").strip()
    if not key and question_type is not None:
        key = str(getattr(question_type, "value", question_type)).strip()
    if not key:
        raise RubricKeyError("The question has no rubric_key and no question type to fall back on.")
    try:
        return rubric.for_key(key)
    except KeyError:
        raise RubricKeyError(
            f"Rubric '{rubric.name}' has no entry for rubric_key '{key}'. Available: {', '.join(rubric.keys)}."
        ) from None


def select_for_question(rubric: Rubric, question: _QuestionLike) -> QuestionRubric:
    """Convenience wrapper for a Question model (or any object with rubric_key and question_type)."""
    return select_question_rubric(rubric, question.rubric_key, question.question_type)
