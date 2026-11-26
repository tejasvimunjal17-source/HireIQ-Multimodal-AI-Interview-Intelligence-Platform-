"""Day 8: validation rules of the question-bank request/response schemas (pure pydantic; no database)."""

import pytest
from pydantic import ValidationError

from app.schemas.interview import QuestionPublic
from app.schemas.question_bank import (
    MAX_SKILLS, ActivationRequest, InterviewCreate, QuestionBankItem, QuestionCreate, normalise_category, normalise_skill, normalise_skill_filter,
)

TEXT = "Explain how database indexes speed up queries."


def q(**overrides):
    return QuestionCreate(**{"text": TEXT, "question_type": "technical", **overrides})


def problems(exc: ValidationError) -> str:
    return " | ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())


# ---------------------------------------------------------------- valid input and normalisation
def test_minimal_question_is_valid_and_optional_fields_default_to_empty():
    question = q()
    assert question.rubric_key is None and question.category is None and question.difficulty is None
    assert question.expected_skills == [] and question.time_limit_seconds is None and question.position is None


def test_full_question_is_normalised():
    question = q(text=f"  {TEXT}  ", rubric_key=" databases ", category="  System Design ", difficulty="hard",
                 expected_skills=["  SQL ", "Query   Planning", "sql", "C++", "node.js"], time_limit_seconds=120, position=3)
    assert question.text == TEXT and question.rubric_key == "databases" and question.category == "system-design"
    assert question.expected_skills == ["sql", "query planning", "c++", "node.js"]  # trimmed, lower-cased, de-duplicated
    assert (question.difficulty, question.time_limit_seconds, question.position) == ("hard", 120, 3)


def test_blank_optional_strings_mean_not_set():
    question = q(rubric_key="   ", category="  ")
    assert question.rubric_key is None and question.category is None


def test_multiline_text_is_allowed():
    assert "\n" in q(text="Describe your approach.\nInclude trade-offs.").text


# ---------------------------------------------------------------- invalid input
@pytest.mark.parametrize("text", ["", "   ", "too short", "x" * 2001, "bad\x00text here", "rtl‮trick in text", "esc\x1b[31m sequence here"])
def test_bad_text_is_rejected(text):
    with pytest.raises(ValidationError) as err:
        q(text=text)
    assert "text" in problems(err.value)


def test_text_length_limits_are_inclusive():
    assert q(text="x" * 10).text == "x" * 10 and q(text="x" * 2000).text == "x" * 2000


@pytest.mark.parametrize("field,value", [
    ("question_type", "mixed"), ("question_type", "Technical"), ("difficulty", "extreme"), ("difficulty", "EASY"),
    ("time_limit_seconds", 9), ("time_limit_seconds", 3601), ("time_limit_seconds", 0), ("time_limit_seconds", -5),
    ("position", 0), ("position", 201), ("rubric_key", "Has Space"), ("rubric_key", "../x"), ("rubric_key", "1abc"),
    ("category", "9lives"), ("category", "a" * 51), ("category", "bad/char"),
    ("expected_skills", ["ok", ""]), ("expected_skills", ["bad\x00"]), ("expected_skills", ["x" * 61]), ("expected_skills", ["<script>"]),
    ("expected_skills", "sql"), ("expected_skills", [1, 2]),
])
def test_invalid_field_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        q(**{field: value})


def test_too_many_skills_is_rejected_but_exactly_the_limit_is_fine():
    assert len(q(expected_skills=[f"skill {i}" for i in range(MAX_SKILLS)]).expected_skills) == MAX_SKILLS
    with pytest.raises(ValidationError, match="at most"):
        q(expected_skills=[f"skill {i}" for i in range(MAX_SKILLS + 1)])


def test_duplicates_do_not_count_towards_the_skill_limit():
    assert q(expected_skills=["sql"] * 30).expected_skills == ["sql"]


def test_unknown_or_privileged_fields_are_rejected_not_ignored():
    for extra in ({"is_active": True}, {"id": "x"}, {"interview_id": "x"}, {"Text": "x"}, {"expected_skill": ["sql"]}):
        with pytest.raises(ValidationError) as err:
            q(**extra)
        assert "Extra inputs are not permitted" in problems(err.value)


def test_missing_required_fields_are_named():
    with pytest.raises(ValidationError) as err:
        QuestionCreate()
    assert "text" in problems(err.value) and "question_type" in problems(err.value)


# ---------------------------------------------------------------- interview creation
def test_interview_defaults_and_normalisation():
    interview = InterviewCreate(title="  Backend Engineer ", rubric_name=" backend-engineer ")
    assert interview.title == "Backend Engineer" and interview.interview_type == "mixed" and interview.description is None
    assert interview.rubric_name == "backend-engineer" and interview.total_time_limit_seconds is None
    assert InterviewCreate(title="T", rubric_name="default", description="   ").description is None


@pytest.mark.parametrize("kwargs", [
    {"title": ""}, {"title": "   "}, {"title": "x" * 201}, {"title": "bad\x00"}, {"rubric_name": "../etc/passwd"},
    {"rubric_name": "Default"}, {"rubric_name": ""}, {"rubric_name": "a" * 65}, {"interview_type": "other"},
    {"total_time_limit_seconds": 59}, {"total_time_limit_seconds": 14401}, {"description": "x" * 2001}, {"description": "bad\x07"},
    {"is_active": True}, {"id": "x"},
])
def test_invalid_interview_input_is_rejected(kwargs):
    base = {"title": "T", "rubric_name": "default"}
    with pytest.raises(ValidationError):
        InterviewCreate(**{**base, **kwargs})


def test_activation_request_needs_a_real_boolean():
    assert ActivationRequest(active=True).active is True
    for bad in ({}, {"active": "maybe"}, {"active": True, "extra": 1}):
        with pytest.raises(ValidationError):
            ActivationRequest(**bad)


# ---------------------------------------------------------------- helpers and privacy
def test_normalisers_are_stable_and_reject_bad_values():
    assert normalise_category("Data Structures") == "data-structures" and normalise_skill("  Machine   Learning ") == "machine learning"
    assert normalise_skill(normalise_skill("A  B")) == "a b"  # idempotent: a stored value matches itself when used as a filter
    for bad in ("", "9x", "a/b"):
        with pytest.raises(ValueError):
            normalise_category(bad)
    for bad in ("", "-x", "a" * 61, "semi;colon", 'quote"'):
        with pytest.raises(ValueError):
            normalise_skill(bad)


def test_skill_filter_accepts_percent_but_storage_still_rejects_it():
    assert normalise_skill_filter("  S%L  ") == "s%l" and normalise_skill_filter("%") == "%"
    assert normalise_skill_filter("Machine   Learning") == "machine learning"
    with pytest.raises(ValueError):
        normalise_skill("s%l")  # stored values stay strict
    with pytest.raises(ValidationError):
        QuestionCreate(text="Explain how indexes work.", question_type="technical", expected_skills=["s%l"])
    for bad in ("", "semi;colon", 'quote"', "a" * 61, "back\\slash"):
        with pytest.raises(ValueError):
            normalise_skill_filter(bad)


def test_candidate_facing_question_schema_has_none_of_the_new_metadata():
    hidden = {"category", "difficulty", "expected_skills", "rubric_key", "interview_title"}
    assert not hidden & set(QuestionPublic.model_fields)


def test_bank_item_serialises_with_empty_defaults():
    item = QuestionBankItem(id="3f2b8c1e-aaaa-4bbb-8ccc-111122223333", interview_id="3f2b8c1e-aaaa-4bbb-8ccc-111122223334",
                            interview_title="T", position=1, text=TEXT, question_type="technical")
    dumped = item.model_dump()
    assert dumped["expected_skills"] == [] and dumped["category"] is None and dumped["difficulty"] is None
