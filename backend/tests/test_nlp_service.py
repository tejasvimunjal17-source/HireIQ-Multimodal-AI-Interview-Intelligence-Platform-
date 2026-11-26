"""Day 5: the NLP orchestrator and its integration with the Day 4 evaluation result. Uses injected fake spaCy/VADER
objects, so it runs without either library, a database or a network."""

import json
import logging
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.schemas.nlp import NlpEnrichment
from app.services.evaluation.pipeline import evaluate_transcript
from app.services.evaluation.providers import MockEvaluationProvider
from app.services.nlp import enrich, enrich_fields
from app.services.nlp import service as nlp_service
from app.services.nlp.spacy_backend import NlpUnavailableError
from app.services.nlp.text_analysis import Tok
from tests.evaluation_samples import RUBRICS_DIR, TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT

ON = SimpleNamespace(nlp_enabled=True, nlp_spacy_model="en_core_web_sm")
OFF = SimpleNamespace(nlp_enabled=False, nlp_spacy_model="en_core_web_sm")
SECRET = "Zorblax-Confidential-Candidate-Sentence"


def noun(text, pos="NOUN"):
    return Tok(text, text.lower(), pos, False, True)


class FakeAnalyzer:
    def analyze(self, text):
        phrases = [(noun("process"),), (noun("thread"),), (noun("race"), noun("condition")), (noun("Kubernetes", "PROPN"),)]
        return phrases, [("Google", "ORG"), ("Kubernetes", "TECHNOLOGY"), ("French", "NORP")], len(text.split())


class BrokenAnalyzer:
    def __init__(self, error=None):
        self.error = error or RuntimeError(SECRET)

    def analyze(self, text):
        raise self.error


def vader(text):
    return {"positive": 0.1, "negative": 0.0, "neutral": 0.9, "compound": 0.4, "label": "positive"}


def run(transcript=TECHNICAL_TRANSCRIPT, settings=ON, **kw):
    kw.setdefault("analyzer", FakeAnalyzer())
    kw.setdefault("sentiment_fn", vader)
    return enrich(transcript, TECHNICAL_QUESTION, settings, **kw)


# ---------------------------------------------------------------- happy path and structure
def test_full_enrichment_has_every_documented_part_and_is_valid_json():
    out = run()
    assert out["status"] == "completed" and out["schema_version"] == 1 and out["errors"] == {}
    assert {k["text"] for k in out["keywords"]} >= {"process", "thread", "race condition", "kubernetes"}
    assert {(e["text"], e["label"]) for e in out["entities"]} == {("Google", "ORG"), ("Kubernetes", "TECHNOLOGY")}
    assert out["sentiment"]["label"] == "positive" and -1 <= out["sentiment"]["compound"] <= 1
    assert out["confidence"]["kind"] == "heuristic" and out["confidence"]["affects_evaluation"] is False
    assert out["word_count"] == len(TECHNICAL_TRANSCRIPT.split())
    NlpEnrichment.model_validate(out)  # round-trips through the schema
    assert json.loads(json.dumps(out)) == out  # plain JSON types only: safe for the JSON column


def test_enrichment_is_deterministic():
    assert run() == run()


# ---------------------------------------------------------------- empty, short and invalid input
@pytest.mark.parametrize("text", ["", "   \n", None, 123])
def test_empty_or_invalid_transcript_is_skipped_not_scored(text):
    out = run(text)
    assert out["status"] == "skipped" and out["word_count"] == 0 and out["errors"] == {"transcript": "empty_transcript"}
    assert out["keywords"] is None and out["sentiment"] is None and out["confidence"] is None


def test_very_short_transcript_is_handled():
    out = run("Yes.")
    assert out["status"] == "completed" and out["confidence"]["label"] == "low"


def test_disabled_nlp_stores_nothing():
    assert run(settings=OFF) is None


# ---------------------------------------------------------------- failure handling
def test_missing_spacy_model_gives_a_partial_result_with_a_code():
    out = run(analyzer=BrokenAnalyzer(NlpUnavailableError("spacy_model_missing", "x")))
    assert out["status"] == "partial" and out["errors"] == {"spacy": "spacy_model_missing"}
    assert out["keywords"] is None and out["entities"] is None
    assert out["sentiment"]["label"] == "positive" and out["confidence"]  # the other parts still ran
    assert "supporting_detail" in out["confidence"]["unavailable"]  # confidence re-weights instead of guessing


def test_sentiment_failure_is_isolated():
    def boom(text):
        raise NlpUnavailableError("vader_not_installed", "x")

    out = run(sentiment_fn=boom)
    assert out["status"] == "partial" and out["errors"] == {"sentiment": "vader_not_installed"}
    assert out["keywords"] and out["confidence"] and out["sentiment"] is None


def test_everything_failing_gives_a_failed_marker_not_an_exception():
    def boom(text):
        raise RuntimeError("x")

    out = run("...", analyzer=BrokenAnalyzer(), sentiment_fn=boom)  # no words: confidence has nothing to assess either
    assert out["status"] == "failed" and set(out["errors"]) == {"spacy", "sentiment"}


def test_invalid_component_output_becomes_a_failed_marker():
    out = run(sentiment_fn=lambda text: {**vader(text), "compound": 5.0})  # outside -1..1: schema must refuse it
    assert out["status"] == "failed" and out["errors"] == {"nlp": "internal_error"}


def test_candidate_text_never_reaches_logs_or_stored_errors(caplog):
    caplog.set_level(logging.DEBUG)
    out = run(f"I used {SECRET} at work.", analyzer=BrokenAnalyzer())
    assert SECRET not in json.dumps(out) and SECRET not in caplog.text


# ---------------------------------------------------------------- integration with the Day 4 result
def _evaluated():
    return evaluate_transcript(
        provider=MockEvaluationProvider(), rubrics_dir=RUBRICS_DIR, rubric_name="default",
        question_text=TECHNICAL_QUESTION, question_type="technical", rubric_key="technical",
        transcript=TECHNICAL_TRANSCRIPT,
    )


def test_enrichment_changes_only_the_nlp_field_of_a_scored_evaluation():
    base = _evaluated().fields
    assert base["nlp_enrichment"] is None  # the Day 4 pipeline itself is untouched
    combined = enrich_fields(base, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, ON, analyzer=FakeAnalyzer(), sentiment_fn=vader)
    assert combined["nlp_enrichment"]["status"] == "completed"
    assert {k: v for k, v in combined.items() if k != "nlp_enrichment"} == {k: v for k, v in base.items() if k != "nlp_enrichment"}
    assert base["nlp_enrichment"] is None  # the input dict was not mutated
    json.dumps(combined)


@pytest.mark.parametrize("sentiment_fn,expected", [
    (lambda t: {"positive": 0.0, "negative": 0.9, "neutral": 0.1, "compound": -0.95, "label": "negative"}, "negative"),
    (lambda t: {"positive": 0.9, "negative": 0.0, "neutral": 0.1, "compound": 0.95, "label": "positive"}, "positive")])
def test_sentiment_and_confidence_never_change_score_or_recommendation(sentiment_fn, expected):
    base = _evaluated().fields
    combined = enrich_fields(base, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, ON, analyzer=FakeAnalyzer(), sentiment_fn=sentiment_fn)
    assert combined["nlp_enrichment"]["sentiment"]["label"] == expected
    for key in ("overall_score", "recommendation", "criteria_scores", "explanation", "evaluation_details"):
        assert combined[key] == base[key]


def test_an_nlp_failure_leaves_the_validated_evaluation_intact():
    base = _evaluated().fields
    combined = enrich_fields(base, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, ON, analyzer=BrokenAnalyzer(), sentiment_fn=vader)
    assert combined["nlp_enrichment"]["status"] == "partial"
    assert {k: v for k, v in combined.items() if k != "nlp_enrichment"} == {k: v for k, v in base.items() if k != "nlp_enrichment"}


def test_even_a_crash_inside_enrich_cannot_escape(monkeypatch):
    def explode(*args, **kwargs):
        raise MemoryError("boom")

    monkeypatch.setattr(nlp_service, "enrich", explode)
    out = enrich_fields({"overall_score": 50.0}, "text", "q", ON)
    assert out["overall_score"] == 50.0 and out["nlp_enrichment"]["status"] == "failed"


def test_disabled_nlp_leaves_the_field_null_as_before_day_5():
    assert enrich_fields(_evaluated().fields, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, OFF)["nlp_enrichment"] is None


# ---------------------------------------------------------------- settings
def _settings(monkeypatch, **env):
    for key in ("ENVIRONMENT", "NLP_ENABLED", "NLP_SPACY_MODEL", "TRANSCRIPTION_PROVIDER", "EVALUATION_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {"DATABASE_URL": "sqlite://", "SECRET_KEY": "x" * 48, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_nlp_settings_defaults_and_a_model_name_can_never_be_a_path(monkeypatch):
    s = _settings(monkeypatch)
    assert s.nlp_enabled is True and s.nlp_spacy_model == "en_core_web_sm"
    assert _settings(monkeypatch, NLP_ENABLED="false").nlp_enabled is False
    for bad in ("../evil", "/tmp/model", "a b", ""):
        with pytest.raises(Exception):
            _settings(monkeypatch, NLP_SPACY_MODEL=bad)
