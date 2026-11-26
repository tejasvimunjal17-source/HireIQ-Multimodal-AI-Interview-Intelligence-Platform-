"""Day 4 Phase 2: the evaluation response schema and evidence grounding (real code, no LLM, no network)."""

import ast
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.evaluation import (
    RECOMMENDATION_VALUES,
    CriterionEvaluation,
    EvaluationContext,
    EvaluationParseError,
    EvaluationResponse,
    parse_evaluation_response,
    quote_is_in_transcript,
    response_json_schema,
    word_sequence,
)
from app.services.rubrics.models import QuestionRubric, ScoreScale
from tests.evaluation_samples import (
    BEHAVIORAL_QUOTES,
    BEHAVIORAL_TRANSCRIPT,
    TECHNICAL_QUOTES,
    TECHNICAL_TRANSCRIPT,
    context_for,
    default_rubric,
    valid_response,
)

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def ctx() -> EvaluationContext:
    return context_for("technical", TECHNICAL_TRANSCRIPT)


def reject(raw, context, *expected: str) -> EvaluationParseError:
    """Parse must fail; every `expected` fragment must appear in the problems. Returns the error."""
    with pytest.raises(EvaluationParseError) as info:
        parse_evaluation_response(raw, context)
    text = "\n".join(info.value.problems)
    for fragment in expected:
        assert fragment in text, f"{fragment!r} not in problems:\n{text}"
    return info.value


# ---------------------------------------------------------------- valid responses
def test_valid_technical_response_is_accepted_from_a_dict(ctx):
    result = parse_evaluation_response(valid_response(), ctx)
    assert isinstance(result, EvaluationResponse)
    assert [c.criterion_key for c in result.criteria_scores] == [
        "technical_accuracy", "depth_of_understanding", "problem_solving_approach", "communication_clarity"]
    assert result.overall_score == 7.5 and result.recommendation == "proceed"
    assert all(isinstance(c, CriterionEvaluation) and c.score == 7 for c in result.criteria_scores)


def test_valid_behavioral_response_is_accepted_from_json_text_and_bytes():
    ctx = context_for("behavioral", BEHAVIORAL_TRANSCRIPT)
    text = json.dumps(valid_response("behavioral", BEHAVIORAL_QUOTES))
    assert parse_evaluation_response(text, ctx).criteria_scores[0].criterion_key == "situation_and_structure"
    assert len(parse_evaluation_response(text.encode("utf-8"), ctx).criteria_scores) == 4


def test_a_verified_response_is_immutable(ctx):
    result = parse_evaluation_response(valid_response(), ctx)
    assert isinstance(result.criteria_scores, tuple) and isinstance(result.strengths, tuple)
    assert isinstance(result.criteria_scores[0].evidence_quotes, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        result.recommendation = "reject"
    with pytest.raises(TypeError):
        result.criteria_scores[0] = result.criteria_scores[1]


def test_boundary_scores_are_accepted(ctx):
    data = valid_response()
    data["criteria_scores"][0]["score"] = 10
    data["criteria_scores"][1]["score"] = 1
    data["overall_score"] = 10
    assert parse_evaluation_response(data, ctx).overall_score == 10.0


def test_empty_strengths_and_improvements_are_allowed_but_the_fields_are_required(ctx):
    data = valid_response()
    data["strengths"], data["areas_for_improvement"] = [], []
    assert parse_evaluation_response(data, ctx).strengths == ()
    del data["strengths"]
    reject(data, ctx, "strengths: Field required")


def test_the_input_dict_is_not_modified(ctx):
    data = valid_response()
    before = copy.deepcopy(data)
    parse_evaluation_response(data, ctx)
    assert data == before


# ---------------------------------------------------------------- missing fields
@pytest.mark.parametrize("field", ["overall_score", "criteria_scores", "strengths", "areas_for_improvement", "summary", "recommendation"])
def test_missing_top_level_field_is_rejected(ctx, field):
    data = valid_response()
    del data[field]
    reject(data, ctx, f"{field}: Field required")


@pytest.mark.parametrize("field", ["criterion_key", "score", "explanation", "evidence_quotes"])
def test_missing_criterion_field_is_rejected_with_its_location(ctx, field):
    data = valid_response()
    del data["criteria_scores"][2][field]
    reject(data, ctx, f"criteria_scores.2.{field}: Field required")


def test_empty_object_reports_every_missing_field(ctx):
    error = reject({}, ctx)
    assert len(error.problems) == 6


# ---------------------------------------------------------------- invalid types
@pytest.mark.parametrize("bad", ["7", 7.5, True, False, None, [7], {"v": 7}, 7.0])
def test_score_must_be_a_whole_number(ctx, bad):
    data = valid_response()
    data["criteria_scores"][0]["score"] = bad
    reject(data, ctx, "criteria_scores.0.score")


@pytest.mark.parametrize("bad", ["7", True, None, [7], float("nan"), float("inf")])
def test_overall_score_must_be_a_finite_number(ctx, bad):
    data = valid_response()
    data["overall_score"] = bad
    reject(data, ctx, "overall_score")


@pytest.mark.parametrize("field, bad", [
    ("summary", 5), ("summary", None), ("summary", "   "), ("summary", ["a"]),
    ("strengths", "one string"), ("strengths", [1]), ("areas_for_improvement", {"a": 1}),
    ("criteria_scores", "text"), ("criteria_scores", {}), ("criteria_scores", [[]]),
])
def test_wrong_types_are_rejected(ctx, field, bad):
    data = valid_response()
    data[field] = bad
    reject(data, ctx, f"{field}")


@pytest.mark.parametrize("field, bad", [
    ("explanation", 12), ("explanation", ""), ("explanation", "   "), ("criterion_key", 5), ("criterion_key", "Technical Accuracy"),
    ("evidence_quotes", "a single string"), ("evidence_quotes", [3]), ("evidence_quotes", None),
])
def test_wrong_criterion_field_types_are_rejected(ctx, field, bad):
    data = valid_response()
    data["criteria_scores"][0][field] = bad
    reject(data, ctx, f"criteria_scores.0.{field}")


def test_extra_fields_are_rejected_instead_of_ignored(ctx):
    data = valid_response()
    data["weighted_total"] = 8.2
    reject(data, ctx, "weighted_total: Extra inputs are not permitted")
    data = valid_response()
    data["criteria_scores"][0]["weight"] = 0.35
    reject(data, ctx, "criteria_scores.0.weight: Extra inputs are not permitted")


def test_limits_on_list_sizes_and_text_lengths(ctx):
    data = valid_response()
    data["strengths"] = ["a strength"] * 6
    reject(data, ctx, "strengths")
    data = valid_response()
    data["summary"] = "x" * 2001
    reject(data, ctx, "summary")
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = [TECHNICAL_QUOTES[0]] * 6
    reject(data, ctx, "evidence_quotes")


def test_empty_criteria_list_is_rejected(ctx):
    data = valid_response()
    data["criteria_scores"] = []
    reject(data, ctx, "criteria_scores")


# ---------------------------------------------------------------- scores and the rubric range
@pytest.mark.parametrize("score", [11, 12, 100])
def test_score_outside_the_rubric_range_is_rejected_and_never_clamped(ctx, score):
    data = valid_response()
    data["criteria_scores"][0]["score"] = score
    reject(data, ctx, f"criterion 'technical_accuracy': score {score} is outside the rubric range 0-10")


@pytest.mark.parametrize("score", [101, -1, -5])
def test_score_outside_the_absolute_limits_is_rejected(ctx, score):
    data = valid_response()
    data["criteria_scores"][0]["score"] = score
    reject(data, ctx, "criteria_scores.0.score")


@pytest.mark.parametrize("overall", [10.5, 11, 50])
def test_overall_score_outside_the_rubric_range_is_rejected(ctx, overall):
    data = valid_response()
    data["overall_score"] = overall
    reject(data, ctx, "overall_score", "outside the rubric range 0-10")


def test_the_range_comes_from_the_rubric_scale_not_from_a_constant():
    rubric = default_rubric()
    ctx = EvaluationContext.from_question_rubric(rubric.for_key("technical"), ScoreScale(min=1, max=5), TECHNICAL_TRANSCRIPT)
    data = valid_response(score=4)
    data["overall_score"] = 4
    assert parse_evaluation_response(data, ctx).overall_score == 4
    data["criteria_scores"][0]["score"] = 6
    reject(data, ctx, "score 6 is outside the rubric range 1-5")
    data["criteria_scores"][0]["score"] = 0
    reject(data, ctx, "score 0 is outside the rubric range 1-5")


@pytest.mark.parametrize("overall", [-0.1, -5, 100.5])
def test_overall_score_outside_the_absolute_limits_is_rejected(ctx, overall):
    data = valid_response()
    data["overall_score"] = overall
    reject(data, ctx, "overall_score")


def test_overall_score_is_taken_as_given_and_never_recomputed(ctx):
    data = valid_response(score=9)  # every criterion 9, but the model says 3.0: not our job to "fix" it here
    data["overall_score"] = 3.0
    assert parse_evaluation_response(data, ctx).overall_score == 3.0
    assert set(EvaluationResponse.model_fields) == {
        "overall_score", "criteria_scores", "strengths", "areas_for_improvement", "summary", "recommendation"}


# ---------------------------------------------------------------- criteria vs the rubric
def test_unknown_criterion_is_rejected(ctx):
    data = valid_response()
    data["criteria_scores"][1]["criterion_key"] = "charisma"
    error = reject(data, ctx, "unknown criterion 'charisma'", "missing required criteria: depth_of_understanding")
    assert "allowed: technical_accuracy" in "\n".join(error.problems)


def test_criterion_of_the_other_question_type_is_unknown(ctx):
    data = valid_response()
    data["criteria_scores"][0]["criterion_key"] = "ownership_and_actions"  # a behavioral criterion
    reject(data, ctx, "unknown criterion 'ownership_and_actions'")


def test_duplicate_criteria_are_rejected(ctx):
    data = valid_response()
    data["criteria_scores"][3] = copy.deepcopy(data["criteria_scores"][0])
    reject(data, ctx, "criterion 'technical_accuracy' appears more than once", "missing required criteria: communication_clarity")


def test_missing_required_criterion_is_rejected(ctx):
    data = valid_response()
    data["criteria_scores"].pop()
    reject(data, ctx, "missing required criteria: communication_clarity")


def test_all_criteria_missing_but_one_lists_each_missing_key(ctx):
    data = valid_response()
    data["criteria_scores"] = data["criteria_scores"][:1]
    reject(data, ctx, "missing required criteria: depth_of_understanding, problem_solving_approach, communication_clarity")


def test_criteria_order_does_not_matter(ctx):
    data = valid_response()
    data["criteria_scores"].reverse()
    assert len(parse_evaluation_response(data, ctx).criteria_scores) == 4


# ---------------------------------------------------------------- evidence quotes
def test_valid_verbatim_quote_is_accepted(ctx):
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = ["a crash in one process does not take down the others"]
    assert parse_evaluation_response(data, ctx)


@pytest.mark.parametrize("quote", [
    "A CRASH IN ONE PROCESS DOES NOT TAKE DOWN THE OTHERS",                  # case
    "a  crash in one\nprocess does not   take down the others",              # whitespace
    "“a crash in one process does not take down the others.”",     # curly quotes + full stop
    "you need locks to avoid race conditions,",                              # trailing comma
    "So a process is an independent program in execution",                   # comma removed from "So,"
])
def test_harmless_formatting_differences_in_a_real_quote_are_tolerated(ctx, quote):
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = [quote]
    assert parse_evaluation_response(data, ctx)


@pytest.mark.parametrize("quote", [
    "a process shares memory with every other process on the machine",       # invented
    "threads never need locks because they are isolated",                    # contradicts the answer
    "separate processes for isolation when I need",                          # same words, different order
    "a crash in one process takes down all the others",                      # altered words
    "a crash in one process down the others",                                # words removed in the middle
    "I would use Kubernetes to orchestrate the containers",                  # from a different answer
])
def test_fabricated_or_altered_quotes_are_rejected(ctx, quote):
    data = valid_response()
    data["criteria_scores"][1]["evidence_quotes"] = [quote]
    reject(data, ctx, "criterion 'depth_of_understanding': evidence quote #1 was not found in the transcript")


def test_one_fabricated_quote_among_valid_ones_rejects_the_response(ctx):
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = [TECHNICAL_QUOTES[0], "the candidate also mentioned using Redis", TECHNICAL_QUOTES[1]]
    reject(data, ctx, "evidence quote #2 was not found")


@pytest.mark.parametrize("quote", ["", "   ", "\n"])
def test_empty_evidence_quote_is_rejected(ctx, quote):
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = [quote]
    reject(data, ctx, "criteria_scores.0.evidence_quotes.0")


@pytest.mark.parametrize("quote", ["memory", "share memory", "the", "...", "does not"])
def test_too_short_quotes_do_not_count_as_evidence(ctx, quote):
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = [quote]
    error = reject(data, ctx)
    assert any("too short" in p or "evidence_quotes.0" in p for p in error.problems)


def test_evidence_is_required_for_any_score_above_the_minimum(ctx):
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = []
    reject(data, ctx, "criterion 'technical_accuracy': evidence quotes are required for any score above the minimum (0)")
    data["criteria_scores"][0]["score"] = 1
    reject(data, ctx, "evidence quotes are required")


def test_no_evidence_is_acceptable_only_at_the_minimum_score(ctx):
    data = valid_response()
    data["criteria_scores"][0].update(score=0, evidence_quotes=[],
                                      explanation="The candidate never addressed this; the information is missing.")
    assert parse_evaluation_response(data, ctx).criteria_scores[0].evidence_quotes == ()


def test_a_very_short_answer_can_only_be_quoted_in_full():
    ctx = context_for("technical", "Yes, threads.")
    data = valid_response(quotes=("Yes threads",), score=1)
    data["overall_score"] = 1
    assert parse_evaluation_response(data, ctx)
    data["criteria_scores"][0]["evidence_quotes"] = ["maybe processes"]
    reject(data, ctx, "evidence quote #1 was not found")


def test_a_valid_quote_from_the_wrong_transcript_is_rejected():
    ctx = context_for("technical", BEHAVIORAL_TRANSCRIPT)
    reject(valid_response(), ctx, "was not found in the transcript")


def test_error_messages_never_echo_the_transcript_or_the_quote(ctx):
    secret_quote = "the candidate's home address is 12 Privet Drive"
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = [secret_quote]
    error = reject(data, ctx, "not found")
    shown = str(error) + repr(ctx) + repr(error.problems)
    assert "Privet" not in shown and "global interpreter lock" not in shown and "address space" not in shown


# ---------------------------------------------------------------- recommendation
@pytest.mark.parametrize("value", RECOMMENDATION_VALUES)
def test_each_allowed_recommendation_is_accepted(ctx, value):
    data = valid_response()
    data["recommendation"] = value
    assert parse_evaluation_response(data, ctx).recommendation == value


@pytest.mark.parametrize("value", ["maybe", "PROCEED", "Proceed", " proceed", "", "hire", "pass", None, 1, True, ["proceed"]])
def test_invalid_recommendation_value_is_rejected(ctx, value):
    data = valid_response()
    data["recommendation"] = value
    reject(data, ctx, "recommendation")


def test_recommendation_values_match_the_database_enum():
    """The schema is DB-free, so compare against app/models/enums.py as text (importing it needs SQLAlchemy)."""
    tree = ast.parse((BACKEND / "app" / "models" / "enums.py").read_text(encoding="utf-8"))
    enum_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Recommendation")
    db_values = [stmt.value.value for stmt in enum_class.body if isinstance(stmt, ast.Assign)]
    assert list(RECOMMENDATION_VALUES) == db_values == ["proceed", "hold", "reject"]


# ---------------------------------------------------------------- context is mandatory
def test_response_cannot_be_validated_without_a_context():
    with pytest.raises(ValidationError, match="EvaluationContext"):
        EvaluationResponse.model_validate(valid_response())
    with pytest.raises(ValidationError, match="EvaluationContext"):
        EvaluationResponse.model_validate_json(json.dumps(valid_response()))
    with pytest.raises(ValidationError, match="EvaluationContext"):
        EvaluationResponse.model_validate(valid_response(), context={"transcript": TECHNICAL_TRANSCRIPT})


def test_model_construct_style_shortcuts_are_not_offered_by_the_parser(ctx):
    """The only parser entry point takes a context; there is no overload without one."""
    with pytest.raises(TypeError):
        parse_evaluation_response(valid_response())  # type: ignore[call-arg]


# ---------------------------------------------------------------- raw provider output
@pytest.mark.parametrize("raw, fragment", [
    ("", "response is empty"),
    ("   \n", "response is empty"),
    ("not json at all", "Invalid JSON"),
    ('{"overall_score": 7', "Invalid JSON"),
    ("[]", "object"),
    ("null", "object"),
    ("Sure! Here is the evaluation: {}", "Invalid JSON"),
    ("```json\n" + json.dumps(valid_response()) + "\n```", "Invalid JSON"),   # code fences are NOT stripped
    (123, "response must be JSON text or a JSON object"),
    (None, "response must be JSON text or a JSON object"),
    ([valid_response()], "response must be JSON text or a JSON object"),
])
def test_malformed_provider_output_is_rejected(ctx, raw, fragment):
    reject(raw, ctx, fragment)


def test_oversized_output_is_rejected_before_parsing(ctx):
    reject("x" * 100_001, ctx, "longer than")


def test_json_text_is_validated_as_strictly_as_a_dict(ctx):
    data = valid_response()
    data["criteria_scores"][0]["score"] = "7"
    reject(json.dumps(data), ctx, "criteria_scores.0.score")
    data["criteria_scores"][0]["score"] = 7.5
    reject(json.dumps(data), ctx, "criteria_scores.0.score")


def test_all_contextual_problems_are_reported_together(ctx):
    data = valid_response()
    data["overall_score"] = 12
    data["criteria_scores"][0]["score"] = 11
    data["criteria_scores"][1]["criterion_key"] = "charisma"
    data["criteria_scores"][2]["evidence_quotes"] = ["something the candidate never said at all"]
    data["criteria_scores"][3]["evidence_quotes"] = []
    error = reject(data, ctx, "overall_score 12", "score 11", "unknown criterion 'charisma'", "missing required criteria",
                   "evidence quote #1 was not found", "evidence quotes are required")
    assert len(error.problems) >= 6
    assert str(error).startswith(f"Evaluation response is invalid ({len(error.problems)} problem(s))")


def test_very_many_problems_are_summarised(ctx):
    data = valid_response()
    data["criteria_scores"] = [{"criterion_key": f"unknown_{i}", "score": 1, "explanation": "x", "evidence_quotes": []} for i in range(12)]
    assert "more problem(s)" in str(reject(data, ctx))


# ---------------------------------------------------------------- context object
def test_context_is_built_from_the_rubric():
    rubric = default_rubric()
    ctx = EvaluationContext.from_question_rubric(rubric.for_key("behavioral"), rubric.score_scale, BEHAVIORAL_TRANSCRIPT)
    assert ctx.criteria_keys == ("situation_and_structure", "ownership_and_actions", "results_and_impact", "reflection_and_learning")
    assert (ctx.score_min, ctx.score_max) == (0, 10)


@pytest.mark.parametrize("transcript", ["", "   ", "\n\t", "...", "?!", None, 42])
def test_context_refuses_an_empty_transcript(transcript):
    rubric = default_rubric()
    with pytest.raises(ValueError, match="transcript is empty"):
        EvaluationContext.from_question_rubric(rubric.for_key("technical"), rubric.score_scale, transcript)


def test_context_rejects_inconsistent_rubric_data():
    with pytest.raises(ValueError, match="no criteria"):
        EvaluationContext((), 0, 10, "some words here")
    with pytest.raises(ValueError, match="duplicate"):
        EvaluationContext(("a", "a"), 0, 10, "some words here")
    with pytest.raises(ValueError, match="greater"):
        EvaluationContext(("a",), 5, 5, "some words here")


def test_context_never_prints_the_transcript():
    ctx = context_for("technical", TECHNICAL_TRANSCRIPT)
    assert "address space" not in repr(ctx) and "address space" not in str(ctx)
    with pytest.raises(Exception):
        ctx.score_max = 99  # frozen


# ---------------------------------------------------------------- matching helpers
def test_word_sequence_ignores_case_punctuation_quotes_and_spacing():
    assert word_sequence("  Hello, WORLD!! It’s “fine”.  ") == "hello world it s fine"
    assert word_sequence("...") == ""


def test_quote_matching_requires_whole_words_in_order():
    assert quote_is_in_transcript("share its memory", TECHNICAL_TRANSCRIPT)
    assert not quote_is_in_transcript("hare its memory", TECHNICAL_TRANSCRIPT)       # partial word
    assert not quote_is_in_transcript("memory its share", TECHNICAL_TRANSCRIPT)      # wrong order
    assert not quote_is_in_transcript("cheap to create and communicate quickly but locks", TECHNICAL_TRANSCRIPT)  # skipped words


# ---------------------------------------------------------------- JSON schema for providers
def test_json_schema_describes_the_required_shape():
    schema = response_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"overall_score", "criteria_scores", "strengths", "areas_for_improvement", "summary", "recommendation"}
    assert schema["properties"]["recommendation"]["enum"] == list(RECOMMENDATION_VALUES)
    criterion = schema["$defs"]["CriterionEvaluation"]
    assert set(criterion["required"]) == {"criterion_key", "score", "explanation", "evidence_quotes"}
    assert criterion["properties"]["score"]["type"] == "integer"
    json.dumps(schema)  # serialisable


def test_schema_module_is_independent_of_providers_and_the_database():
    tree = ast.parse((BACKEND / "app" / "schemas" / "evaluation.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    top_level = {name.split(".")[0] for name in imported}
    assert not top_level & {"openai", "google", "requests", "httpx", "sqlalchemy", "celery", "redis"}, top_level
    # The only project module it may use is the rubric model layer (no app.models, app.api, app.workers, app.db).
    assert {name for name in imported if name.startswith("app")} == {"app.services.rubrics.models"}
