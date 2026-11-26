"""Day 8: rubric folder tooling (list/validate every file, describe, key resolution, CLI) and the guarantee that a
rubric added as a plain YAML file works with the unchanged Day 4 evaluation pipeline. No database, no network."""

import copy
from pathlib import Path

import pytest
import yaml

from app.core.config import DEFAULT_RUBRICS_DIR
from app.scripts import validate_rubrics
from app.services.evaluation.pipeline import EvaluationFailure, evaluate_transcript
from app.services.evaluation.providers import MockEvaluationProvider
from app.services.rubrics import load_rubric
from app.services.rubrics.catalog import describe_rubric, list_rubric_names, resolve_rubric_key, validate_rubrics_dir
from tests.evaluation_samples import TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT


def default_data() -> dict:
    return yaml.safe_load((DEFAULT_RUBRICS_DIR / "default.yaml").read_text(encoding="utf-8"))


def write(folder: Path, name: str, data: dict | str) -> Path:
    path = folder / f"{name}.yaml"
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def custom(name: str = "backend-engineer") -> dict:
    """A realistic custom rubric: the default technical block reused under a new key plus a 'databases' block."""
    data = default_data()
    data["name"] = name
    data["description"] = "Rubric for backend engineers."
    data["question_types"]["databases"] = copy.deepcopy(data["question_types"]["technical"])
    data["question_types"]["databases"]["description"] = "SQL and data modelling questions."
    return data


# ---------------------------------------------------------------- backward compatibility
def test_shipped_default_rubric_is_unchanged_in_its_contract():
    rubric = load_rubric("default", DEFAULT_RUBRICS_DIR)
    assert (rubric.name, rubric.version, rubric.score_scale.min, rubric.score_scale.max) == ("default", 1, 0, 10)
    assert rubric.keys == ["behavioral", "technical"]
    weights = {k: {c.key: c.weight for c in rubric.for_key(k).criteria} for k in rubric.keys}
    assert weights["technical"] == {"technical_accuracy": 0.35, "depth_of_understanding": 0.25, "problem_solving_approach": 0.20, "communication_clarity": 0.20}
    assert weights["behavioral"] == {"situation_and_structure": 0.20, "ownership_and_actions": 0.30, "results_and_impact": 0.25, "reflection_and_learning": 0.25}


def test_every_shipped_rubric_file_is_valid():
    reports = validate_rubrics_dir(DEFAULT_RUBRICS_DIR)
    assert reports and all(r.valid for r in reports), [(r.name, r.error) for r in reports if not r.valid]


def test_a_rubric_with_a_different_scale_still_loads_and_validates(tmp_path):
    data = default_data()
    data["name"] = "five-point"
    data["score_scale"] = {"min": 1, "max": 5}
    for block in data["question_types"].values():
        for criterion in block["criteria"]:
            criterion["score_ranges"] = [
                {"min": 1, "max": 1, "label": "Poor", "description": "Poor."},
                {"min": 2, "max": 3, "label": "Fair", "description": "Fair."},
                {"min": 4, "max": 5, "label": "Good", "description": "Good."},
            ]
    write(tmp_path, "five-point", data)
    assert validate_rubrics_dir(tmp_path)[0].valid


# ---------------------------------------------------------------- folder validation
def test_every_file_is_reported_and_a_bad_one_does_not_hide_the_good_ones(tmp_path):
    write(tmp_path, "good", {**default_data(), "name": "good"})
    bad_weights = default_data(); bad_weights["name"] = "bad-weights"
    bad_weights["question_types"]["technical"]["criteria"][0]["weight"] = 0.5
    write(tmp_path, "bad-weights", bad_weights)
    write(tmp_path, "broken-yaml", "name: [unclosed")
    wrong_name = default_data(); wrong_name["name"] = "something-else"
    write(tmp_path, "mismatch", wrong_name)
    write(tmp_path, "Bad_Name", {**default_data(), "name": "bad_name"})
    (tmp_path / "notes.txt").write_text("ignored: not a rubric file")
    by_name = {r.name: r for r in validate_rubrics_dir(tmp_path)}
    assert set(by_name) == {"good", "bad-weights", "broken-yaml", "mismatch", "Bad_Name"}
    assert by_name["good"].valid and by_name["good"].rubric is not None
    assert not by_name["bad-weights"].valid and "weights must sum to 1.0" in by_name["bad-weights"].error
    assert not by_name["broken-yaml"].valid and "not valid YAML" in by_name["broken-yaml"].error
    assert not by_name["mismatch"].valid and "must match the file name" in by_name["mismatch"].error
    assert not by_name["Bad_Name"].valid and "not a valid rubric name" in by_name["Bad_Name"].error


def test_missing_or_empty_folder_gives_an_empty_list_not_a_crash(tmp_path):
    assert validate_rubrics_dir(tmp_path / "nope") == [] and validate_rubrics_dir(tmp_path) == []
    assert list_rubric_names(tmp_path / "nope") == []


def test_errors_never_contain_secrets_or_file_content(tmp_path):
    write(tmp_path, "leaky", "name: leaky\napi_key: sk-live-ABCDEF1234567890\n")
    (report,) = validate_rubrics_dir(tmp_path)
    assert not report.valid and "sk-live" not in report.error


# ---------------------------------------------------------------- description and key resolution
def test_describe_exposes_names_weights_and_scale_but_no_prompt_material():
    info = describe_rubric(load_rubric("default", DEFAULT_RUBRICS_DIR))
    assert info["score_scale"] == {"min": 0, "max": 10} and set(info["rubric_keys"]) == {"behavioral", "technical"}
    first = info["rubric_keys"]["technical"]["criteria"][0]
    assert first == {"key": "technical_accuracy", "name": "Technical accuracy", "weight": 0.35}
    text = yaml.safe_dump(info)
    assert "strong_examples" not in text and "score_ranges" not in text and "Correctly distinguishes" not in text


def test_resolve_rubric_key_matches_the_pipeline_rules(tmp_path):
    write(tmp_path, "backend-engineer", custom())
    rubric = load_rubric("backend-engineer", tmp_path)
    assert resolve_rubric_key(rubric, "databases", "technical") == "databases"
    assert resolve_rubric_key(rubric, None, "technical") == "technical"
    assert resolve_rubric_key(rubric, "  ", "behavioral") == "behavioral"
    with pytest.raises(KeyError, match="Available: behavioral, databases, technical"):
        resolve_rubric_key(rubric, "networking", "technical")


# ---------------------------------------------------------------- command line
def test_cli_reports_ok_and_exit_code_0_for_the_shipped_rubrics(capsys):
    assert validate_rubrics.main(["x"]) == 0
    assert "OK       default" in capsys.readouterr().out


def test_cli_exit_codes_for_invalid_and_empty_folders(tmp_path, capsys):
    assert validate_rubrics.main(["x", str(tmp_path)]) == 2
    write(tmp_path, "bad", "name: bad\n")
    assert validate_rubrics.main(["x", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "INVALID  bad" in out and "0 valid, 1 invalid" in out


# ---------------------------------------------------------------- unchanged Day 4 pipeline uses a newly added rubric
def run_pipeline(folder: Path, name: str, key: str | None):
    return evaluate_transcript(
        provider=MockEvaluationProvider(), rubrics_dir=folder, rubric_name=name, question_text=TECHNICAL_QUESTION,
        question_type="technical", rubric_key=key, transcript=TECHNICAL_TRANSCRIPT,
    )


def test_pipeline_scores_with_a_rubric_added_only_as_a_yaml_file(tmp_path):
    write(tmp_path, "backend-engineer", custom())
    result = run_pipeline(tmp_path, "backend-engineer", "databases")
    assert result.fields["rubric_name"] == "backend-engineer"
    assert set(result.fields["criteria_scores"]) == {c["key"] for c in custom()["question_types"]["databases"]["criteria"]}
    assert 0 <= result.fields["overall_score"] <= 100


def test_weights_edited_in_yaml_change_the_stored_score_without_code_changes(tmp_path):
    base = custom()
    write(tmp_path, "backend-engineer", base)
    before = run_pipeline(tmp_path, "backend-engineer", "databases").fields["overall_score"]
    shifted = copy.deepcopy(base)
    weights = [0.05, 0.05, 0.05, 0.85]  # still sums to 1.0; the mock gives different fake scores per criterion index
    for criterion, weight in zip(shifted["question_types"]["databases"]["criteria"], weights):
        criterion["weight"] = weight
    write(tmp_path, "backend-engineer", shifted)
    assert run_pipeline(tmp_path, "backend-engineer", "databases").fields["overall_score"] != before


def test_pipeline_rejects_a_broken_or_unknown_rubric_with_a_clear_failure_code(tmp_path):
    broken = custom(); broken["question_types"]["databases"]["criteria"][0]["weight"] = 0.9
    write(tmp_path, "backend-engineer", broken)
    with pytest.raises(EvaluationFailure) as invalid:
        run_pipeline(tmp_path, "backend-engineer", "databases")
    assert invalid.value.code == "rubric_invalid"
    with pytest.raises(EvaluationFailure) as missing:
        run_pipeline(tmp_path, "does-not-exist", "technical")
    assert missing.value.code == "rubric_missing"
    write(tmp_path, "backend-engineer", custom())
    with pytest.raises(EvaluationFailure) as unknown_key:
        run_pipeline(tmp_path, "backend-engineer", "networking")
    assert unknown_key.value.code == "rubric_key_unsupported"
