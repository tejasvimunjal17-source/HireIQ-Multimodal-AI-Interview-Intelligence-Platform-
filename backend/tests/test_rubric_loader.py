"""Day 4 foundation: loading YAML rubrics and selecting technical / behavioral criteria (real code, no mocks).

The tests use the real default.yaml shipped in backend/config/rubrics and temporary YAML files.
No database, Redis or network is needed.
"""

import copy
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.services.rubrics import (
    Rubric,
    RubricFormatError,
    RubricKeyError,
    RubricNotFoundError,
    RubricValidationError,
    load_rubric,
    parse_rubric_text,
    select_for_question,
    select_question_rubric,
)
from app.services.rubrics.loader import MAX_RUBRIC_FILE_BYTES

BACKEND = Path(__file__).resolve().parents[1]
RUBRICS_DIR = BACKEND / "config" / "rubrics"


class Kind(StrEnum):
    """Stand-in with the same values as app.models.enums.QuestionType (keeps this file free of DB imports)."""

    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"


def bands(prefix: str = "b") -> list[dict]:
    return [
        {"min": 0, "max": 4, "label": f"{prefix}-low", "description": "Weak answer."},
        {"min": 5, "max": 7, "label": f"{prefix}-mid", "description": "Adequate answer."},
        {"min": 8, "max": 10, "label": f"{prefix}-high", "description": "Strong answer."},
    ]


def criterion(key: str, weight: float) -> dict:
    return {
        "key": key, "name": key.title(), "description": f"About {key}.", "weight": weight,
        "strong_examples": ["A strong example."], "weak_examples": ["A weak example."], "score_ranges": bands(),
    }


def valid_data() -> dict:
    return {
        "name": "custom", "version": 1, "description": "Test rubric.",
        "score_scale": {"min": 0, "max": 10},
        "question_types": {
            "technical": {"description": "Tech.", "criteria": [criterion("accuracy", 0.6), criterion("depth", 0.4)]},
            "behavioral": {"description": "Behav.", "criteria": [criterion("ownership", 1.0)]},
        },
    }


def write_rubric(directory: Path, data: dict | str, name: str = "custom") -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------- valid loading
def test_default_rubric_file_loads_and_is_internally_consistent():
    rubric = load_rubric("default", RUBRICS_DIR)
    assert isinstance(rubric, Rubric)
    assert rubric.name == "default" and rubric.version >= 1
    assert rubric.keys == ["behavioral", "technical"]
    for key in ("technical", "behavioral"):
        question = rubric.for_key(key)
        assert question.weight_total == pytest.approx(1.0, abs=1e-9)
        assert len(question.criteria) >= 3
        for criterion_ in question.criteria:
            assert criterion_.description and criterion_.strong_examples and criterion_.weak_examples
            assert criterion_.score_ranges[0].min == rubric.score_scale.min
            assert criterion_.score_ranges[-1].max == rubric.score_scale.max


def test_valid_custom_rubric_loads_from_a_string_or_path_directory(tmp_path):
    write_rubric(tmp_path, valid_data())
    assert load_rubric("custom", tmp_path).keys == ["behavioral", "technical"]
    assert load_rubric("custom", str(tmp_path)).name == "custom"


def test_loaded_rubric_is_immutable(tmp_path):
    write_rubric(tmp_path, valid_data())
    rubric = load_rubric("custom", tmp_path)
    with pytest.raises(Exception):
        rubric.version = 2


def test_weights_come_from_yaml_not_from_python(tmp_path):
    data = valid_data()
    data["question_types"]["technical"]["criteria"][0]["weight"] = 0.9
    data["question_types"]["technical"]["criteria"][1]["weight"] = 0.1
    write_rubric(tmp_path, data)
    weights = [c.weight for c in load_rubric("custom", tmp_path).for_key("technical").criteria]
    assert weights == [0.9, 0.1]


# ---------------------------------------------------------------- missing / unsafe / unreadable files
def test_missing_rubric_file_is_reported_with_its_expected_path(tmp_path):
    with pytest.raises(RubricNotFoundError) as info:
        load_rubric("does_not_exist", tmp_path)
    assert "does_not_exist.yaml" in str(info.value)


@pytest.mark.parametrize("bad_name", ["../default", "default/../x", "/etc/passwd", "Default", "", "a b", "x" * 65, "..", "d.yaml"])
def test_unsafe_or_malformed_rubric_names_are_rejected_before_touching_the_disk(tmp_path, bad_name):
    with pytest.raises(RubricNotFoundError):
        load_rubric(bad_name, tmp_path)


def test_rubric_name_must_be_text():
    with pytest.raises(RubricNotFoundError):
        load_rubric(None, RUBRICS_DIR)  # type: ignore[arg-type]


def test_directory_with_the_rubric_name_is_not_a_file(tmp_path):
    (tmp_path / "custom.yaml").mkdir()
    with pytest.raises(RubricNotFoundError):
        load_rubric("custom", tmp_path)


def test_file_name_and_inner_name_must_match(tmp_path):
    write_rubric(tmp_path, valid_data(), name="other")  # inner name is "custom"
    with pytest.raises(RubricValidationError, match="must match the file name"):
        load_rubric("other", tmp_path)


def test_oversized_file_is_rejected(tmp_path):
    write_rubric(tmp_path, "# " + "x" * (MAX_RUBRIC_FILE_BYTES + 10) + "\n")
    with pytest.raises(RubricFormatError, match="larger than"):
        load_rubric("custom", tmp_path)


def test_non_utf8_file_is_rejected(tmp_path):
    (tmp_path / "custom.yaml").write_bytes(b"name: \xff\xfe\x00bad\n")
    with pytest.raises(RubricFormatError, match="UTF-8"):
        load_rubric("custom", tmp_path)


# ---------------------------------------------------------------- invalid YAML
def test_invalid_yaml_syntax_gives_a_line_number(tmp_path):
    write_rubric(tmp_path, "name: custom\nversion: [1, 2\nquestion_types: {\n")
    with pytest.raises(RubricFormatError, match=r"not valid YAML at line \d+"):
        load_rubric("custom", tmp_path)


@pytest.mark.parametrize("text", ["- just\n- a list\n", "42\n", "", "plain text\n"])
def test_top_level_must_be_a_mapping(tmp_path, text):
    write_rubric(tmp_path, text)
    with pytest.raises(RubricFormatError, match="mapping"):
        load_rubric("custom", tmp_path)


def test_duplicate_keys_are_rejected_instead_of_silently_keeping_the_last(tmp_path):
    text = yaml.safe_dump(valid_data()).replace("name: custom\n", "name: custom\nname: custom\n", 1)
    write_rubric(tmp_path, text)
    with pytest.raises(RubricFormatError, match="duplicate key 'name'"):
        load_rubric("custom", tmp_path)


def test_python_object_tags_are_refused_and_never_executed(tmp_path):
    marker = tmp_path / "pwned"
    # With an unsafe YAML loader this line would CALL os.mkdir and create the marker folder.
    write_rubric(tmp_path, f"name: !!python/object/apply:os.mkdir ['{marker}']\n")
    with pytest.raises(RubricFormatError):
        load_rubric("custom", tmp_path)
    assert not marker.exists()


# ---------------------------------------------------------------- rubric_key selection
def test_technical_rubric_selection_uses_the_technical_block():
    rubric = load_rubric("default", RUBRICS_DIR)
    selected = select_question_rubric(rubric, "technical")
    assert selected is rubric.question_types["technical"]
    assert "technical_accuracy" in [c.key for c in selected.criteria]


def test_behavioral_rubric_selection_uses_the_behavioral_block():
    rubric = load_rubric("default", RUBRICS_DIR)
    selected = select_question_rubric(rubric, "behavioral")
    assert selected is rubric.question_types["behavioral"]
    assert "ownership_and_actions" in [c.key for c in selected.criteria]
    assert selected is not rubric.question_types["technical"]


def test_technical_and_behavioral_blocks_have_different_criteria():
    rubric = load_rubric("default", RUBRICS_DIR)
    technical = {c.key for c in rubric.for_key("technical").criteria}
    behavioral = {c.key for c in rubric.for_key("behavioral").criteria}
    assert technical.isdisjoint(behavioral)


def test_selection_follows_question_rubric_key_first():
    rubric = load_rubric("default", RUBRICS_DIR)
    question = SimpleNamespace(rubric_key="behavioral", question_type=Kind.TECHNICAL)
    assert select_for_question(rubric, question) is rubric.question_types["behavioral"]


@pytest.mark.parametrize("kind", list(Kind))
@pytest.mark.parametrize("empty_key", [None, "", "   "])
def test_empty_rubric_key_falls_back_to_the_question_type(kind, empty_key):
    rubric = load_rubric("default", RUBRICS_DIR)
    question = SimpleNamespace(rubric_key=empty_key, question_type=kind)
    assert select_for_question(rubric, question) is rubric.question_types[kind.value]


def test_unknown_rubric_key_lists_the_available_keys_and_never_guesses():
    rubric = load_rubric("default", RUBRICS_DIR)
    with pytest.raises(RubricKeyError) as info:
        select_question_rubric(rubric, "leadership", Kind.TECHNICAL)
    assert "leadership" in str(info.value) and "behavioral, technical" in str(info.value)


def test_no_key_and_no_type_is_an_error():
    rubric = load_rubric("default", RUBRICS_DIR)
    with pytest.raises(RubricKeyError):
        select_question_rubric(rubric, None, None)


def test_parse_rubric_text_validates_without_a_file():
    rubric = parse_rubric_text(yaml.safe_dump(copy.deepcopy(valid_data())))
    assert rubric.name == "custom"
