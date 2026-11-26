"""Day 4 Phase 1 correction: a loaded rubric is immutable ALL THE WAY DOWN (real code, no mocks).

The review found that frozen models still exposed mutable nested lists and dicts. These tests try to
modify every kind of nested collection and prove it is impossible, that the rubric is not aliased to the
data it was built from, and that it is still fully usable (iteration, selection, serialization, copying).
"""

import copy
import pickle
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from app.services.rubrics import Rubric, load_rubric, select_question_rubric
from tests.test_rubric_loader import valid_data

RUBRICS_DIR = Path(__file__).resolve().parents[1] / "config" / "rubrics"


@pytest.fixture
def rubric() -> Rubric:
    return load_rubric("default", RUBRICS_DIR)


def walk(value, path="rubric"):
    """Yield (path, value) for every object reachable from a rubric, descending into models, tuples, mappings."""
    yield path, value
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from walk(getattr(value, name), f"{path}.{name}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from walk(item, f"{path}[{key!r}]")
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


# ---------------------------------------------------------------- nothing mutable is reachable
def test_no_mutable_list_dict_or_set_is_reachable_anywhere_in_a_loaded_rubric(rubric):
    mutable = [(path, type(v).__name__) for path, v in walk(rubric) if isinstance(v, (list, dict, set, bytearray))]
    assert mutable == []


def test_the_walker_really_visits_the_whole_tree(rubric):
    paths = [path for path, _ in walk(rubric)]
    assert any(".criteria[0].strong_examples[0]" in p for p in paths)
    assert any(".score_ranges[4]" in p for p in paths)
    assert len(paths) > 200  # default.yaml has 8 criteria x (5 bands + examples + fields)


def test_nested_collections_have_the_expected_immutable_types(rubric):
    technical = rubric.for_key("technical")
    criterion = technical.criteria[0]
    assert isinstance(rubric.question_types, Mapping) and not isinstance(rubric.question_types, dict)
    assert isinstance(technical.criteria, tuple)
    assert isinstance(criterion.strong_examples, tuple)
    assert isinstance(criterion.weak_examples, tuple)
    assert isinstance(criterion.score_ranges, tuple)


# ---------------------------------------------------------------- every modification attempt fails
def test_question_types_mapping_cannot_be_modified(rubric):
    with pytest.raises(TypeError):
        rubric.question_types["extra"] = rubric.for_key("technical")
    with pytest.raises(TypeError):
        rubric.question_types["technical"] = rubric.for_key("behavioral")
    with pytest.raises(TypeError):
        del rubric.question_types["technical"]
    for method in ("pop", "popitem", "update", "clear", "setdefault"):
        assert not hasattr(rubric.question_types, method), method
    assert rubric.keys == ["behavioral", "technical"]


def test_criteria_tuple_cannot_be_modified(rubric):
    technical = rubric.for_key("technical")
    before = tuple(technical.criteria)
    with pytest.raises(TypeError):
        technical.criteria[0] = technical.criteria[1]
    with pytest.raises(TypeError):
        del technical.criteria[0]
    for method in ("append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse"):
        assert not hasattr(technical.criteria, method), method
    assert technical.criteria == before


@pytest.mark.parametrize("field", ["strong_examples", "weak_examples", "score_ranges"])
def test_criterion_collections_cannot_be_modified(rubric, field):
    criterion = rubric.for_key("behavioral").criteria[0]
    collection = getattr(criterion, field)
    before = tuple(collection)
    with pytest.raises(TypeError):
        collection[0] = collection[-1]
    assert not hasattr(collection, "append") and not hasattr(collection, "sort")
    assert getattr(criterion, field) == before


def test_attributes_cannot_be_reassigned_at_any_level(rubric):
    technical = rubric.for_key("technical")
    criterion = technical.criteria[0]
    targets = [
        (rubric, "name", "hacked"), (rubric, "version", 99), (rubric, "question_types", {}),
        (rubric.score_scale, "max", 5), (technical, "criteria", ()), (technical, "description", "x"),
        (criterion, "weight", 0.99), (criterion, "key", "other"), (criterion, "strong_examples", ()),
        (criterion.score_ranges[0], "min", 3), (criterion.score_ranges[0], "label", "x"),
    ]
    for obj, attribute, value in targets:
        with pytest.raises(ValidationError, match="frozen"):
            setattr(obj, attribute, value)
    assert rubric.name == "default" and criterion.weight == 0.35


def test_weights_still_sum_to_one_after_the_attempted_modifications(rubric):
    technical = rubric.for_key("technical")
    with pytest.raises(TypeError):
        technical.criteria[0] = technical.criteria[1]
    with pytest.raises(ValidationError):
        technical.criteria[0].weight = 0.9
    assert technical.weight_total == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------- no aliasing with the source data
def test_changing_the_source_dict_after_validation_does_not_change_the_rubric():
    data = valid_data()
    rubric = Rubric.model_validate(data)
    data["name"] = "changed"
    data["question_types"]["technical"]["criteria"][0]["weight"] = 0.01
    data["question_types"]["technical"]["criteria"][0]["strong_examples"].append("injected")
    data["question_types"]["technical"]["criteria"][0]["score_ranges"].clear()
    data["question_types"]["new_type"] = data["question_types"]["technical"]
    del data["question_types"]["behavioral"]
    assert rubric.name == "custom" and rubric.keys == ["behavioral", "technical"]
    criterion = rubric.for_key("technical").criteria[0]
    assert criterion.weight == 0.6
    assert criterion.strong_examples == ("A strong example.",)
    assert len(criterion.score_ranges) == 3


def test_changing_a_serialized_copy_does_not_change_the_rubric(rubric):
    dumped = rubric.model_dump()
    dumped["question_types"]["technical"]["criteria"] = ()
    dumped["question_types"].clear()
    assert rubric.keys == ["behavioral", "technical"]
    assert len(rubric.for_key("technical").criteria) == 4


# ---------------------------------------------------------------- still validates strictly
@pytest.mark.parametrize("field, value", [
    # Short strings on purpose: "abc" would become ("a", "b", "c") - three valid-looking examples - if text
    # were converted to a tuple, so only a real type check can reject it.
    ("strong_examples", "abc"),
    ("weak_examples", "ab"),
    ("weak_examples", {"a": "dict"}),
    ("score_ranges", "abc"),
])
def test_text_or_dict_is_not_silently_turned_into_a_tuple(field, value):
    data = valid_data()
    data["question_types"]["technical"]["criteria"][0][field] = value
    with pytest.raises(ValidationError, match=field):
        Rubric.model_validate(data)


def test_criteria_must_be_a_list_and_question_types_a_mapping():
    data = valid_data()
    data["question_types"]["technical"]["criteria"] = "not a list"
    with pytest.raises(ValidationError, match="criteria"):
        Rubric.model_validate(data)
    data = valid_data()
    data["question_types"] = [("technical", data["question_types"]["technical"])]
    with pytest.raises(ValidationError, match="question_types"):
        Rubric.model_validate(data)


def test_length_limits_still_apply_to_the_frozen_collections():
    data = valid_data()
    data["question_types"]["technical"]["criteria"] = []
    with pytest.raises(ValidationError, match="at least 1"):
        Rubric.model_validate(data)
    data = valid_data()
    data["question_types"] = {}
    with pytest.raises(ValidationError, match="question_types"):
        Rubric.model_validate(data)


# ---------------------------------------------------------------- still usable (prompt builder needs this)
def test_loaded_rubric_can_be_iterated_indexed_and_selected(rubric):
    technical = select_question_rubric(rubric, "technical")
    assert [c.key for c in technical.criteria][:2] == ["technical_accuracy", "depth_of_understanding"]
    assert technical.criteria[0].score_ranges[0].label == "Poor"
    assert technical.criterion("communication_clarity").weight == 0.20
    assert sum(1 for _ in technical.criteria) == len(technical.criteria) == 4
    assert sorted(rubric.question_types) == rubric.keys
    assert "technical" in rubric.question_types and len(rubric.question_types) == 2
    assert [k for k, _ in rubric.question_types.items()] == list(rubric.question_types.keys())
    assert select_question_rubric(rubric, "behavioral") is rubric.question_types["behavioral"]


def test_order_of_criteria_and_bands_matches_the_yaml_file(rubric):
    raw = yaml.safe_load((RUBRICS_DIR / "default.yaml").read_text(encoding="utf-8"))
    for key in ("technical", "behavioral"):
        assert [c.key for c in rubric.for_key(key).criteria] == [c["key"] for c in raw["question_types"][key]["criteria"]]
    first = raw["question_types"]["technical"]["criteria"][0]
    assert [r.label for r in rubric.for_key("technical").criteria[0].score_ranges] == [r["label"] for r in first["score_ranges"]]


def test_serialization_round_trips_through_json(rubric):
    as_json = rubric.model_dump_json()
    assert Rubric.model_validate_json(as_json) == rubric
    assert Rubric.model_validate(rubric.model_dump()) == rubric
    assert isinstance(rubric.model_dump()["question_types"], dict)


def test_copy_deepcopy_model_copy_and_pickle_work_on_a_loaded_rubric(rubric):
    assert copy.copy(rubric) == rubric
    assert copy.deepcopy(rubric) == rubric
    assert rubric.model_copy(deep=True) == rubric
    restored = pickle.loads(pickle.dumps(rubric))
    assert restored == rubric and restored is not rubric
    assert isinstance(restored.question_types, Mapping) and not isinstance(restored.question_types, dict)
    with pytest.raises(TypeError):
        restored.question_types["x"] = 1
