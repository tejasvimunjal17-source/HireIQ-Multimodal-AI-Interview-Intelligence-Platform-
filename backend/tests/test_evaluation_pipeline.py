"""Day 4 Phase 3: scoring, providers, provider selection, the validation pipeline and the pure state rules.
No database, no network: the OpenAI provider talks to a fake HTTP session."""

import json
import math
from types import SimpleNamespace

import pytest
import requests
from pydantic import SecretStr

from app.schemas.evaluation import parse_evaluation_response
from app.services.evaluation import persistence
from app.services.evaluation.pipeline import EvaluationFailure, backoff_seconds, evaluate_transcript
from app.services.evaluation.prompt_builder import build_evaluation_prompt
from app.services.evaluation.providers import (
    EvaluationProviderError, MockEvaluationProvider, OpenAIEvaluationProvider, ProviderOutput, get_evaluation_provider,
)
from app.services.evaluation.scoring import ScoringError, calculate_score, to_percentage
from app.services.evaluation.states import ResponseState as R, classify_response, decide_session_status
from tests.evaluation_samples import (
    BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT, RUBRICS_DIR, TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT,
    default_rubric, valid_response,
)

KEY = "sk-test-SECRET-123"


def _prompt(key="technical", question=TECHNICAL_QUESTION, transcript=TECHNICAL_TRANSCRIPT):
    return build_evaluation_prompt(rubric=default_rubric(), question_text=question, transcript=transcript, rubric_key=key)


def _evaluate(provider, key="technical", question=TECHNICAL_QUESTION, transcript=TECHNICAL_TRANSCRIPT, rubric_name="default"):
    return evaluate_transcript(
        provider=provider, rubrics_dir=RUBRICS_DIR, rubric_name=rubric_name, question_text=question,
        question_type=key, rubric_key=key, transcript=transcript,
    )


class Fixed(SimpleNamespace):
    """A provider that returns a fixed raw text."""
    name = "fixed"
    model = "fixed-1"

    def evaluate(self, prompt):
        return ProviderOutput(raw_text=self.text, provider="fixed", model="fixed-1")


def _with_scores(scores, key="technical"):
    data = valid_response(key)
    for item, score in zip(data["criteria_scores"], scores):
        item["score"] = score
    return data


# ------------------------------------------------------------------ weighted scoring
def test_weighted_score_uses_yaml_weights_and_converts_to_percent():
    rubric = default_rubric()
    parsed = parse_evaluation_response(json.dumps(_with_scores([8, 7, 6, 9])), _prompt().context)
    breakdown = calculate_score(parsed, rubric.for_key("technical"), rubric.score_scale)
    # 0.35*8 + 0.25*7 + 0.20*6 + 0.20*9 = 2.8 + 1.75 + 1.2 + 1.8 = 7.55  ->  75.5 / 100
    assert math.isclose(breakdown.weighted_score, 7.55, abs_tol=1e-9)
    assert math.isclose(breakdown.overall_score_100, 75.5, abs_tol=1e-9)
    assert [c.key for c in breakdown.criteria] == [c.key for c in rubric.for_key("technical").criteria]
    assert [c.weight for c in breakdown.criteria] == [c.weight for c in rubric.for_key("technical").criteria]


def test_scale_extremes_map_to_0_and_100_and_midpoint_to_50():
    assert to_percentage(0, 0, 10) == 0 and to_percentage(10, 0, 10) == 100 and to_percentage(5, 0, 10) == 50
    assert to_percentage(3, 1, 5) == 50  # works for any YAML scale, not only 0-10


def test_model_holistic_score_does_not_change_the_result():
    rubric = default_rubric()
    a, b = _with_scores([8, 7, 6, 9]), _with_scores([8, 7, 6, 9])
    b["overall_score"] = 1.0
    context = _prompt().context
    scored = [calculate_score(parse_evaluation_response(json.dumps(x), context), rubric.for_key("technical"), rubric.score_scale) for x in (a, b)]
    assert scored[0].overall_score_100 == scored[1].overall_score_100


def test_scoring_does_not_round_and_persistence_rounds_once():
    result = _evaluate(Fixed(text=json.dumps(_with_scores([7, 7, 7, 8]))))
    exact = result.breakdown.overall_score_100
    assert math.isclose(exact, 72.0, abs_tol=1e-9)  # unrounded float from the weights; rounding happens in persistence
    assert result.fields["overall_score"] == round(exact, 2)
    assert 0 <= result.fields["overall_score"] <= 100


def test_out_of_range_score_is_rejected_not_clamped():
    rubric = default_rubric()
    parsed = parse_evaluation_response(json.dumps(valid_response()), _prompt().context)
    narrow = SimpleNamespace(min=0, max=5)  # a rubric that only allows 0-5 must reject the 7s
    with pytest.raises(ScoringError):
        calculate_score(parsed, rubric.for_key("technical"), narrow)


# ------------------------------------------------------------------ persistence mapping
def test_persisted_fields_keep_criteria_weights_explanations_evidence_and_recommendation():
    result = _evaluate(Fixed(text=json.dumps(valid_response())))
    f = result.fields
    assert set(f["criteria_scores"]) == {c.key for c in default_rubric().for_key("technical").criteria}
    for key, row in f["criteria_scores"].items():
        assert set(row) == {"score", "weight", "weighted_contribution", "explanation", "evidence_quotes"}
        assert row["evidence_quotes"] and row["explanation"]
    assert f["recommendation"] == "proceed"
    assert f["evaluation_details"]["strengths"] and f["evaluation_details"]["rubric_key"] == "technical"
    assert f["evaluation_details"]["model_overall_score"] == 7.5
    assert f["nlp_enrichment"] is None and f["llm_provider"] == "fixed" and f["rubric_name"] == "default"
    json.dumps(f)  # everything is JSON-serialisable


# ------------------------------------------------------------------ mock provider
@pytest.mark.parametrize("key,question,transcript", [
    ("technical", TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT), ("behavioral", BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT)])
def test_mock_provider_is_deterministic_and_passes_full_validation(key, question, transcript):
    first = _evaluate(MockEvaluationProvider(), key, question, transcript)
    second = _evaluate(MockEvaluationProvider(), key, question, transcript)
    assert first.fields == second.fields
    assert first.provider == "mock" and first.fields["llm_model"] == "mock-evaluator-1"
    assert set(first.fields["criteria_scores"]) == {c.key for c in default_rubric().for_key(key).criteria}


def test_mock_provider_handles_a_very_short_transcript():
    result = _evaluate(MockEvaluationProvider(), transcript="I do not know.")
    assert result.fields["overall_score"] >= 0


def test_mock_provider_makes_no_network_call(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: pytest.fail("network used"))
    _evaluate(MockEvaluationProvider())


# ------------------------------------------------------------------ OpenAI provider (fake HTTP)
class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, raw_error=False):
        self.status_code, self._body, self.headers, self._raw_error = status, body, headers or {}, raw_error

    def json(self):
        if self._raw_error:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, result):
        self.result, self.calls = result, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _ok(content, model="gpt-4o-2024-08-06", finish="stop"):
    return FakeResponse(200, {"model": model, "choices": [{"finish_reason": finish, "message": {"content": content}}]})



def test_openai_request_shape_and_success():
    session = FakeSession(_ok('{"a": 1}'))
    provider = OpenAIEvaluationProvider(api_key=KEY, model="gpt-4o", base_url="https://example.test/v1/", session=session)
    out = provider.evaluate(_prompt())
    url, kwargs = session.calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert kwargs["headers"] == {"Authorization": f"Bearer {KEY}"}
    body = kwargs["json"]
    assert body["model"] == "gpt-4o" and body["response_format"] == {"type": "json_object"} and body["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == _prompt().system and "JSON" in body["messages"][1]["content"]
    assert out.raw_text == '{"a": 1}' and out.provider == "openai" and out.model == "gpt-4o-2024-08-06"


def test_openai_without_key_is_a_permanent_configuration_error():
    with pytest.raises(EvaluationProviderError) as info:
        OpenAIEvaluationProvider(api_key=None, model="gpt-4o")
    assert info.value.code == "provider_not_configured" and not info.value.retryable


@pytest.mark.parametrize("result,code,retryable", [
    (requests.Timeout("t"), "provider_timeout", True),
    (requests.ConnectionError(f"boom https://x?key={KEY}"), "provider_unreachable", True),
    (FakeResponse(429, {}, {"Retry-After": "7"}), "rate_limited", True),
    (FakeResponse(429, {"error": {"code": "insufficient_quota"}}), "quota_exceeded", False),
    (FakeResponse(503), "provider_error", True),
    (FakeResponse(401), "provider_auth", False),
    (FakeResponse(400), "provider_rejected", False),
    (FakeResponse(200, {"unexpected": 1}), "provider_bad_response", True),
    (FakeResponse(200, raw_error=True), "provider_bad_response", True),
    (_ok(""), "provider_bad_response", True),
    (_ok("{", finish="length"), "provider_bad_response", True),
    (FakeResponse(200, {"choices": [{"message": {"content": None, "refusal": "no"}}]}), "provider_refused", False),
])
def test_openai_failures_are_classified_and_never_leak_the_key(result, code, retryable):
    provider = OpenAIEvaluationProvider(api_key=KEY, model="gpt-4o", session=FakeSession(result))
    with pytest.raises(EvaluationProviderError) as info:
        provider.evaluate(_prompt())
    assert (info.value.code, info.value.retryable) == (code, retryable)
    assert KEY not in str(info.value) and KEY not in repr(provider)
    assert TECHNICAL_TRANSCRIPT not in str(info.value)


def test_rate_limit_honours_retry_after():
    provider = OpenAIEvaluationProvider(api_key=KEY, model="m", session=FakeSession(FakeResponse(429, {}, {"Retry-After": "42"})))
    with pytest.raises(EvaluationProviderError) as info:
        provider.evaluate(_prompt())
    assert info.value.retry_after == 42.0
    assert backoff_seconds(0, 5, 42.0) == 42 and backoff_seconds(0, 5) == 5 and backoff_seconds(10, 5) == 300


# ------------------------------------------------------------------ provider selection
def _settings(provider, key=None):
    return SimpleNamespace(evaluation_provider=provider, openai_api_key=SecretStr(key) if key else None,
                           evaluation_model="gpt-4o", openai_base_url="https://api.openai.com/v1", evaluation_timeout_seconds=60)


def test_provider_selection():
    assert isinstance(get_evaluation_provider(_settings("mock")), MockEvaluationProvider)
    chosen = get_evaluation_provider(_settings("openai", KEY))
    assert isinstance(chosen, OpenAIEvaluationProvider) and chosen.model == "gpt-4o" and KEY not in repr(chosen)
    with pytest.raises(EvaluationProviderError) as missing:
        get_evaluation_provider(_settings("openai"))
    assert missing.value.code == "provider_not_configured"
    with pytest.raises(EvaluationProviderError) as unknown:
        get_evaluation_provider(_settings("gemini"))
    assert unknown.value.code == "provider_unsupported" and not unknown.value.retryable


# ------------------------------------------------------------------ validation failures (never persisted)
def _failure(text, **kw):
    with pytest.raises(EvaluationFailure) as info:
        _evaluate(Fixed(text=text), **kw)
    return info.value


def test_invalid_json_is_a_bounded_retryable_failure():
    f = _failure("this is not json")
    assert (f.code, f.retryable, f.max_retries) == ("invalid_json", True, 1)


def test_code_fenced_json_is_rejected():
    assert _failure("```json\n" + json.dumps(valid_response()) + "\n```").code == "invalid_json"


def test_schema_violation_is_invalid_response():
    data = valid_response()
    data["recommendation"] = "maybe"
    assert _failure(json.dumps(data)).code == "invalid_response"
    data = valid_response()
    data["criteria_scores"] = data["criteria_scores"][:-1]  # a criterion is missing
    assert _failure(json.dumps(data)).code == "invalid_response"
    data = valid_response()
    data["criteria_scores"][0]["score"] = 11  # outside the 0-10 YAML scale
    assert _failure(json.dumps(data)).code == "invalid_response"


def test_invented_quote_is_an_evidence_failure():
    data = valid_response()
    data["criteria_scores"][0]["evidence_quotes"] = ["the candidate said something they never said"]
    f = _failure(json.dumps(data))
    assert f.code == "evidence_invalid" and f.retryable
    assert "never said" not in str(f)


def test_failure_messages_never_contain_transcript_or_output():
    f = _failure(json.dumps({"summary": TECHNICAL_TRANSCRIPT}))
    assert TECHNICAL_TRANSCRIPT not in str(f)


def test_provider_error_is_translated_with_its_retry_flags():
    class Broken(Fixed):
        def evaluate(self, prompt):
            raise EvaluationProviderError("rate_limited", "slow down", retryable=True, retry_after=9)

    with pytest.raises(EvaluationFailure) as info:
        _evaluate(Broken())
    assert (info.value.code, info.value.retryable, info.value.retry_after) == ("rate_limited", True, 9)


@pytest.mark.parametrize("kwargs,code", [
    ({"rubric_name": "does_not_exist"}, "rubric_missing"),
    ({"key": "no_such_key"}, "rubric_key_unsupported"),
    ({"transcript": "   "}, "transcript_missing"),
    ({"transcript": "word " * 5000}, "transcript_too_long"),
])
def test_permanent_configuration_and_input_failures_are_not_retryable(kwargs, code):
    f = _failure(json.dumps(valid_response()), **kwargs)
    assert f.code == code and not f.retryable


# ------------------------------------------------------------------ transcription / evaluation state rules
def test_answer_classification():
    c = classify_response
    assert c("pending", False, 0, "pending") == R.TRANSCRIPTION_OPEN
    assert c("processing", False, 0, "pending") == R.TRANSCRIPTION_OPEN
    assert c("failed", False, 0, "pending") == R.TRANSCRIPTION_FAILED
    assert c("completed", True, 0, "pending") == R.NO_SPEECH
    assert c("completed", False, 0, "pending") == R.MISSING_TRANSCRIPT
    assert c("completed", False, 50, "pending") == R.EVALUATION_OPEN
    assert c("completed", False, 50, "processing") == R.EVALUATION_OPEN
    assert c("completed", False, 50, "completed") == R.EVALUATED
    assert c("completed", False, 50, "failed") == R.EVALUATION_FAILED


def test_session_status_decisions():
    d = decide_session_status
    assert d([]) is None
    assert d([R.EVALUATED, R.TRANSCRIPTION_OPEN]) == "processing"  # never EVALUATED while anything is unfinished
    assert d([R.EVALUATED, R.EVALUATION_OPEN]) == "processing"
    assert d([R.EVALUATED, R.EVALUATED]) == "evaluated"
    assert d([R.EVALUATED, R.NO_SPEECH]) == "evaluated"  # no speech is a system outcome, not a failure
    assert d([R.NO_SPEECH, R.NO_SPEECH]) == "failed"  # nothing could be evaluated
    assert d([R.EVALUATED, R.TRANSCRIPTION_FAILED]) == "failed"
    assert d([R.EVALUATED, R.EVALUATION_FAILED]) == "failed"
    assert d([R.EVALUATED, R.MISSING_TRANSCRIPT]) == "failed"
    assert d([R.TRANSCRIPTION_FAILED, R.EVALUATION_OPEN]) == "processing"


# ------------------------------------------------------------------ stabilization: no silent clamping
def _breakdown(overall):
    from app.services.evaluation.scoring import ScoreBreakdown
    return ScoreBreakdown(criteria=(), weighted_score=overall / 10, overall_score_100=overall, score_min=0, score_max=10)


def _fields_for(overall):
    prompt = _prompt()
    parsed = parse_evaluation_response(json.dumps(valid_response()), prompt.context)
    return persistence.build_evaluation_fields(parsed=parsed, breakdown=_breakdown(overall), prompt=prompt, provider="p", model="m")


@pytest.mark.parametrize("bad", [100.5, 100.01, -0.5, -1e-6, float("nan")])
def test_out_of_range_overall_score_is_an_error_not_clamped(bad):
    with pytest.raises(ScoringError):
        _fields_for(bad)


@pytest.mark.parametrize("noise,expected", [(100.0 + 1e-12, 100.0), (-1e-12, 0.0), (75.5, 75.5)])
def test_only_floating_point_noise_is_tolerated(noise, expected):
    assert _fields_for(noise)["overall_score"] == expected


def test_pipeline_turns_a_scoring_error_into_a_permanent_controlled_failure(monkeypatch):
    def boom(**kwargs):
        raise ScoringError("x")

    monkeypatch.setattr("app.services.evaluation.pipeline.build_evaluation_fields", boom)
    f = _failure(json.dumps(valid_response()))
    assert (f.code, f.retryable) == ("scoring_invalid", False)


def test_extreme_scores_stay_inside_0_100_through_the_whole_pipeline():
    for score in (0, 10):
        data = valid_response()
        for item in data["criteria_scores"]:
            item["score"] = score
            item["evidence_quotes"] = [] if score == 0 else item["evidence_quotes"]
        result = _evaluate(Fixed(text=json.dumps(data)))
        assert result.fields["overall_score"] == (0.0 if score == 0 else 100.0)


def test_mock_quotes_survive_punctuation_only_tokens():
    result = _evaluate(MockEvaluationProvider(), transcript="- - Yes, I use threads - for I/O bound work, - and processes for isolation.")
    assert result.fields["criteria_scores"]
