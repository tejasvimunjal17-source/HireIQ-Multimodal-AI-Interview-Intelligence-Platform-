"""Operator-facing helpers around the rubric folder (Day 8): list and validate every rubric file, summarise one for
the question-bank API, and resolve a question's rubric key. Pure functions: no database. They reuse the Day 4
loader, so the rules are exactly the ones the evaluation pipeline enforces; nothing is re-implemented here."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.rubrics.loader import RUBRIC_SUFFIX, RubricError, load_rubric
from app.services.rubrics.models import NAME_RE, Rubric


@dataclass(frozen=True)
class RubricFileReport:
    name: str
    valid: bool
    rubric: Rubric | None = None
    error: str = ""  # operator message (first problem lines); never file contents


def list_rubric_names(rubrics_dir: Path | str) -> list[str]:
    """File stems of *.yaml files directly inside the folder (names that cannot be valid rubric names are still listed,
    so that validation can report them instead of silently skipping a broken file)."""
    folder = Path(rubrics_dir)
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.iterdir() if p.is_file() and p.suffix == RUBRIC_SUFFIX)


def validate_rubrics_dir(rubrics_dir: Path | str) -> list[RubricFileReport]:
    """Load every rubric file through the real loader. Never raises for a bad file: it is reported."""
    reports: list[RubricFileReport] = []
    for name in list_rubric_names(rubrics_dir):
        if not NAME_RE.match(name):
            reports.append(RubricFileReport(name, False, error="File name is not a valid rubric name (lowercase letters, digits, '_' or '-')."))
            continue
        try:
            reports.append(RubricFileReport(name, True, rubric=load_rubric(name, rubrics_dir)))
        except RubricError as exc:
            reports.append(RubricFileReport(name, False, error=str(exc)))
    return reports


def describe_rubric(rubric: Rubric) -> dict[str, Any]:
    """Names, weights and scale only. Examples and band descriptions (the evaluation prompt material) are not included."""
    return {
        "name": rubric.name, "version": rubric.version, "description": rubric.description,
        "score_scale": {"min": rubric.score_scale.min, "max": rubric.score_scale.max},
        "rubric_keys": {
            key: {
                "description": block.description,
                "criteria": [{"key": c.key, "name": c.name, "weight": c.weight} for c in block.criteria],
            }
            for key, block in sorted(rubric.question_types.items())
        },
    }


def resolve_rubric_key(rubric: Rubric, rubric_key: str | None, question_type: Any) -> str:
    """The key the evaluation pipeline will use for this question: Question.rubric_key, else the question type.
    Raises KeyError (with the available keys in the message) when the rubric has no such entry."""
    key = (rubric_key or "").strip() or str(getattr(question_type, "value", question_type)).strip()
    if key not in rubric.question_types:
        raise KeyError(f"Rubric '{rubric.name}' has no entry for rubric_key '{key}'. Available: {', '.join(rubric.keys)}.")
    return key
