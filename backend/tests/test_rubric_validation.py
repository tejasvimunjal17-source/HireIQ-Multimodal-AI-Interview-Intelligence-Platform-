"""Day 4 foundation: rubric validation rules - required fields, weights, score ranges (real code, no mocks)."""

import copy

import pytest
import yaml

from app.services.rubrics import RubricValidationError, parse_rubric_text
from tests.test_rubric_loader import criterion, valid_data


def parse(data: dict):
    return parse_rubric_text(yaml.safe_dump(data), source="custom")


def invalid(data: dict, match: str) -> str:
    with pytest.raises(RubricValidationError, match=match) as info:
        parse(data)
    return str(info.value)


def tech(data: dict) -> dict:
    return data["question_types"]["technical"]


def first_criterion(data: dict) -> dict:
    return tech(data)["criteria"][0]


def test_valid_data_is_accepted():
    assert parse(valid_data()).keys == ["behavioral", "technical"]


# ---------------------------------------------------------------- required fields and structure
@pytest.mark.parametrize("field", ["name", "version", "description", "score_scale", "question_types"])
def test_missing_top_level_field_is_reported_by_name(field):
    data = valid_data()
    del data[field]
    assert field in invalid(data, "Field required")


@pytest.mark.parametrize("field", ["key", "name", "description", "weight", "strong_examples", "weak_examples", "score_ranges"])
def test_missing_criterion_field_is_reported_with_its_location(field):
    data = valid_data()
    del first_criterion(data)[field]
    message = invalid(data, "Field required")
    assert f"question_types.technical.criteria.0.{field}" in message


def test_missing_criteria_list_is_rejected():
    data = valid_data()
    del tech(data)["criteria"]
    assert "question_types.technical.criteria" in invalid(data, "Field required")


def test_empty_criteria_list_is_rejected():
    data = valid_data()
    tech(data)["criteria"] = []
    assert "criteria" in invalid(data, "at least 1")


def test_no_question_types_is_rejected():
    data = valid_data()
    data["question_types"] = {}
    invalid(data, "question_types")


def test_misspelled_field_is_rejected_rather_than_ignored():
    data = valid_data()
    first_criterion(data)["wieght"] = first_criterion(data).pop("weight")
    message = invalid(data, "Extra inputs are not permitted")
    assert "wieght" in message and "weight" in message  # also reports the now-missing real field


@pytest.mark.parametrize("bad_key", ["Technical", "1abc", "has space", "", "a-b"])
def test_question_type_and_criterion_keys_must_be_simple_lowercase_identifiers(bad_key):
    data = valid_data()
    data["question_types"][bad_key] = data["question_types"].pop("technical")
    invalid(data, "question_types")
    data = valid_data()
    first_criterion(data)["key"] = bad_key
    invalid(data, "criteria.0.key")


def test_examples_must_not_be_empty_or_blank():
    data = valid_data()
    first_criterion(data)["strong_examples"] = []
    invalid(data, "strong_examples")
    data = valid_data()
    first_criterion(data)["weak_examples"] = ["   "]
    invalid(data, "weak_examples")


def test_text_fields_must_be_text_not_numbers():
    data = valid_data()
    first_criterion(data)["description"] = 123
    invalid(data, "criteria.0.description")


def test_all_problems_are_listed_together():
    data = valid_data()
    del data["description"]
    first_criterion(data)["weight"] = -1
    message = invalid(data, "2 problem")
    assert "description" in message and "criteria.0.weight" in message


# ---------------------------------------------------------------- weights
@pytest.mark.parametrize("weight", [0, -0.1, 1.5, "0.5", True, False, None, [0.5], float("nan"), float("inf")])
def test_invalid_individual_weights_are_rejected(weight):
    data = valid_data()
    tech(data)["criteria"] = [criterion("only", 1.0)]
    tech(data)["criteria"][0]["weight"] = weight
    invalid(data, "criteria.0.weight")


def test_weights_not_totalling_one_are_rejected_with_the_actual_sum():
    data = valid_data()
    tech(data)["criteria"] = [criterion("a", 0.5), criterion("b", 0.4)]
    message = invalid(data, "sum to 1.0")
    assert "sum to 0.9" in message and "a=0.5" in message and "b=0.4" in message


def test_weights_summing_above_one_are_rejected():
    data = valid_data()
    tech(data)["criteria"] = [criterion("a", 0.7), criterion("b", 0.5)]
    invalid(data, "sum to 1.2")


def test_invalid_weights_are_never_silently_normalised():
    data = valid_data()
    tech(data)["criteria"] = [criterion("a", 0.2), criterion("b", 0.2)]
    with pytest.raises(RubricValidationError, match="never normalised"):
        parse(data)


@pytest.mark.parametrize(
    "weights",
    [[0.1, 0.2, 0.3, 0.4], [0.333333, 0.333333, 0.333334], [0.35, 0.25, 0.2, 0.2], [1], [1.0]],
)
def test_floating_point_noise_and_integers_are_accepted(weights):
    data = valid_data()
    tech(data)["criteria"] = [criterion(f"c{i}", w) for i, w in enumerate(weights)]
    assert parse(data).for_key("technical").weight_total == pytest.approx(1.0, abs=1e-9)


def test_total_just_outside_the_tolerance_is_rejected():
    data = valid_data()
    tech(data)["criteria"] = [criterion("a", 0.5), criterion("b", 0.4999)]  # sums to 0.9999
    invalid(data, "sum to")


def test_every_question_type_is_checked_independently():
    data = valid_data()
    data["question_types"]["behavioral"]["criteria"][0]["weight"] = 0.5
    assert "question_types.behavioral" in invalid(data, "sum to")


def test_duplicate_criterion_keys_are_rejected():
    data = valid_data()
    tech(data)["criteria"] = [criterion("same", 0.5), criterion("same", 0.5)]
    invalid(data, "duplicate criterion keys: same")


# ---------------------------------------------------------------- score scale and ranges
@pytest.mark.parametrize("scale", [{"min": 5, "max": 5}, {"min": 10, "max": 0}, {"min": -1, "max": 10},
                                   {"min": 0, "max": 101}, {"min": 0, "max": 10.5}, {"min": "0", "max": 10}, {"min": 0}])
def test_invalid_score_scale_is_rejected(scale):
    data = valid_data()
    data["score_scale"] = scale
    invalid(data, "score_scale")


def set_ranges(data: dict, ranges: list[dict]) -> None:
    first_criterion(data)["score_ranges"] = ranges


def r(low: int, high: int, label: str = "x") -> dict:
    return {"min": low, "max": high, "label": label, "description": "d"}


def test_ranges_with_a_gap_are_rejected():
    data = valid_data()
    set_ranges(data, [r(0, 3, "low"), r(5, 10, "high")])
    message = invalid(data, "gap between")
    assert "criteria[accuracy]" in message and "'low'" in message and "'high'" in message


def test_overlapping_ranges_are_rejected():
    data = valid_data()
    set_ranges(data, [r(0, 5, "low"), r(5, 10, "high")])
    invalid(data, "overlap")


def test_ranges_must_start_at_the_scale_minimum():
    data = valid_data()
    set_ranges(data, [r(1, 5, "low"), r(6, 10, "high")])
    invalid(data, "first range must start at the scale minimum 0")


def test_ranges_must_end_at_the_scale_maximum():
    data = valid_data()
    set_ranges(data, [r(0, 5, "low"), r(6, 9, "high")])
    invalid(data, "last range must end at the scale maximum 10")


def test_range_beyond_the_scale_is_rejected():
    data = valid_data()
    set_ranges(data, [r(0, 5, "low"), r(6, 12, "high")])
    invalid(data, "last range must end at the scale maximum 10")


def test_range_with_min_above_max_is_rejected():
    data = valid_data()
    set_ranges(data, [r(0, 5, "low"), r(9, 6, "bad"), r(10, 10, "top")])
    invalid(data, "min \\(9\\) greater than max \\(6\\)")


@pytest.mark.parametrize("bad", [5.5, "5", None, True])
def test_range_bounds_must_be_whole_numbers(bad):
    data = valid_data()
    set_ranges(data, [r(0, 4, "low"), {**r(5, 10, "high"), "min": bad}])
    invalid(data, "score_ranges")


def test_a_single_range_is_not_enough():
    data = valid_data()
    set_ranges(data, [r(0, 10, "all")])
    invalid(data, "score_ranges")


def test_unsorted_but_valid_ranges_are_accepted():
    data = valid_data()
    set_ranges(data, [r(8, 10, "high"), r(0, 4, "low"), r(5, 7, "mid")])
    assert len(parse(data).for_key("technical").criteria[0].score_ranges) == 3


def test_ranges_follow_a_non_default_scale():
    data = valid_data()
    data["score_scale"] = {"min": 1, "max": 5}
    for question in data["question_types"].values():
        for item in question["criteria"]:
            item["score_ranges"] = [r(1, 2, "low"), r(3, 3, "mid"), r(4, 5, "high")]
    assert parse(data).score_scale.max == 5


def test_validation_does_not_mutate_the_input():
    data = valid_data()
    before = copy.deepcopy(data)
    parse(data)
    assert data == before
