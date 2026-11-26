"""Day 4 Phase 3: engine, dispatch, Celery task, session coordination and migration 0003, on the SQLite
stand-in. The Celery task runs in-process with Task.apply() (eager): real task code, NO real broker/worker.
The provider is the deterministic mock or a scripted fake; no real OpenAI call is made anywhere here."""

import json
import uuid

import pytest
import sqlalchemy as sa

from app.core.config import get_settings
from app.models import (
    CandidateResponse, Evaluation, EvaluationStatus, InterviewSession, Recommendation, SessionStatus,
    TranscriptionStatus,
)
from app.services import evaluation_dispatch
from app.services.evaluation import engine
from app.services.evaluation.providers import EvaluationProviderError, MockEvaluationProvider, ProviderOutput
from app.workers.evaluation_tasks import evaluate_response
from tests.builders import make_response, reload
from tests.evaluation_samples import TECHNICAL_TRANSCRIPT, valid_response

TASK = "eval-task-1"


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("EVALUATION_PROVIDER", "mock")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def ready(session_factory):
    """A transcribed answer with an evaluation task id, in a SUBMITTED session. Returns (response_id, session_id)."""
    def create(**fields):
        defaults = dict(transcription_status=TranscriptionStatus.COMPLETED, transcript=TECHNICAL_TRANSCRIPT,
                        evaluation_task_id=TASK)
        status = fields.pop("status", TranscriptionStatus.COMPLETED)
        task_id = defaults.pop("evaluation_task_id")
        with session_factory() as db:
            response, session = make_response(db, task_id="t", status=status, **{**{k: v for k, v in defaults.items() if k != "transcription_status"}, **fields})
            response.evaluation_task_id = task_id
            session.status = SessionStatus.SUBMITTED
            db.commit()
            return response.id, session.id
    return create


class Scripted:
    """Returns/raises the scripted outcomes in order; the last one repeats. Counts the calls."""
    name, model = "fixed", "fixed-1"

    def __init__(self, *script, error=None):
        self.script = list(script) if script else [error]
        self.calls = 0

    def evaluate(self, prompt):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return ProviderOutput(raw_text=item, provider=self.name, model=self.model)


def count(factory, model=Evaluation):
    with factory() as db:
        return db.scalar(sa.select(sa.func.count()).select_from(model))


# ---------------------------------------------------------------- engine.run
def test_run_persists_a_validated_evaluation_and_settles_the_session(session_factory, settings, ready):
    rid, sid = ready()  # the only answer of the session
    outcome = engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider())
    assert outcome.as_dict() == {"status": "evaluated", "code": ""}
    with session_factory() as db:
        row = db.scalar(sa.select(Evaluation).where(Evaluation.response_id == rid))
        assert 0 <= row.overall_score <= 100 and row.recommendation in set(Recommendation)
        assert row.llm_provider == "mock" and row.llm_model == "mock-evaluator-1" and row.rubric_name == "default"
        # Day 5: the engine now fills nlp_enrichment (deliberate change; Day 4 asserted None). Whatever NLP libraries
        # are installed, a schema-versioned dict is stored and the evaluation itself is complete.
        assert isinstance(row.nlp_enrichment, dict) and row.nlp_enrichment["schema_version"] == 1 and row.explanation
        assert all({"score", "weight", "explanation", "evidence_quotes"} <= set(v) for v in row.criteria_scores.values())
        assert db.get(CandidateResponse, rid).evaluation_status == EvaluationStatus.COMPLETED
        assert db.get(InterviewSession, sid).status == SessionStatus.EVALUATED


def test_duplicate_delivery_does_not_evaluate_twice(session_factory, settings, ready):
    rid, _ = ready()
    provider = Scripted(json.dumps(valid_response()))
    assert engine.run(session_factory, rid, TASK, settings, provider).status == "evaluated"
    again = engine.run(session_factory, rid, TASK, settings, provider)
    assert again.as_dict() == {"status": "skipped", "code": "not_owner"}
    assert provider.calls == 1 and count(session_factory) == 1


def test_a_task_that_does_not_own_the_answer_does_nothing(session_factory, settings, ready):
    rid, _ = ready()
    provider = Scripted(json.dumps(valid_response()))
    assert engine.run(session_factory, rid, "someone-else", settings, provider).code == "not_owner"
    assert provider.calls == 0 and count(session_factory) == 0


def test_evaluation_never_starts_before_transcription_completes(session_factory, settings, ready):
    for status in (TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING, TranscriptionStatus.FAILED):
        rid, _ = ready(status=status)
        provider = Scripted(json.dumps(valid_response()))
        assert engine.run(session_factory, rid, TASK, settings, provider).code == "not_owner"
        assert provider.calls == 0
    assert count(session_factory) == 0


def test_no_speech_is_skipped_not_scored(session_factory, settings, ready):
    rid, sid = ready(no_speech_detected=True, transcript="")
    provider = Scripted(json.dumps(valid_response()))
    assert engine.run(session_factory, rid, TASK, settings, provider).as_dict() == {"status": "skipped", "code": "no_speech"}
    assert provider.calls == 0 and count(session_factory) == 0
    with session_factory() as db:
        response = db.get(CandidateResponse, rid)
        assert (response.evaluation_status, response.evaluation_error) == (EvaluationStatus.SKIPPED, "no_speech")
        assert db.get(InterviewSession, sid).status == SessionStatus.FAILED  # nothing evaluable in the whole session


def test_missing_transcript_is_a_permanent_failure(session_factory, settings, ready):
    rid, _ = ready(transcript=None)
    outcome = engine.run(session_factory, rid, TASK, settings, Scripted("{}"))
    assert outcome.as_dict() == {"status": "failed", "code": "transcript_missing"}
    with session_factory() as db:
        assert db.get(CandidateResponse, rid).evaluation_status == EvaluationStatus.FAILED


def test_invalid_model_output_is_never_stored(session_factory, settings, ready):
    rid, _ = ready()
    with pytest.raises(engine.EvaluationFailure) as info:
        engine.run(session_factory, rid, TASK, settings, Scripted("not json"))
    assert info.value.code == "invalid_json" and info.value.retryable
    assert count(session_factory) == 0
    with session_factory() as db:  # still claimed by the task so that a retry can continue
        assert db.get(CandidateResponse, rid).evaluation_status == EvaluationStatus.PROCESSING


def test_permanent_provider_failure_is_recorded(session_factory, settings, ready):
    rid, _ = ready()
    error = EvaluationProviderError("provider_auth", "no", retryable=False)
    assert engine.run(session_factory, rid, TASK, settings, Scripted(error)).code == "provider_auth"
    with session_factory() as db:
        response = db.get(CandidateResponse, rid)
        assert (response.evaluation_status, response.evaluation_error) == (EvaluationStatus.FAILED, "provider_auth")


def test_missing_api_key_from_the_provider_factory_is_a_permanent_failure(session_factory, settings, ready, monkeypatch):
    def no_key(_settings):
        raise EvaluationProviderError("provider_not_configured", "OPENAI_API_KEY is not set on the server.", retryable=False)

    monkeypatch.setattr("app.services.evaluation.engine.get_evaluation_provider", no_key)
    rid, _ = ready()
    assert engine.run(session_factory, rid, TASK, settings).as_dict() == {"status": "failed", "code": "provider_not_configured"}
    assert reload_status(session_factory, rid) == EvaluationStatus.FAILED


def test_unique_constraint_blocks_a_second_evaluation_row(session_factory, settings, ready):
    rid, _ = ready()
    engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider())
    with session_factory() as db:  # simulate a lost status flag + a redelivered task
        db.execute(sa.update(CandidateResponse).where(CandidateResponse.id == rid).values(evaluation_status=EvaluationStatus.PENDING))
        db.commit()
    assert engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider()).code == "already_evaluated"
    assert count(session_factory) == 1


# ---------------------------------------------------------------- dispatch
def test_dispatch_queues_once_and_is_duplicate_safe(session_factory, evaluation_enqueued):
    with session_factory() as db:
        response, _ = make_response(db, status=TranscriptionStatus.COMPLETED, transcript=TECHNICAL_TRANSCRIPT)
        rid = response.id
    first = evaluation_dispatch.dispatch_evaluation(rid, session_factory)
    second = evaluation_dispatch.dispatch_evaluation(rid, session_factory)
    assert first and second == first and evaluation_enqueued == [(rid, first)]


@pytest.mark.parametrize("status", [TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING, TranscriptionStatus.FAILED])
def test_dispatch_waits_for_transcription(session_factory, evaluation_enqueued, status):
    with session_factory() as db:
        response, _ = make_response(db, status=status)
        rid = response.id
    assert evaluation_dispatch.dispatch_evaluation(rid, session_factory) is None and evaluation_enqueued == []


def test_dispatch_records_no_speech_without_queueing(session_factory, evaluation_enqueued):
    with session_factory() as db:
        response, _ = make_response(db, status=TranscriptionStatus.COMPLETED, transcript="", no_speech_detected=True)
        rid = response.id
    assert evaluation_dispatch.dispatch_evaluation(rid, session_factory) is None and evaluation_enqueued == []
    assert reload_status(session_factory, rid) == EvaluationStatus.SKIPPED


def test_dispatch_undoes_the_claim_when_the_broker_is_down(session_factory, monkeypatch):
    def boom(rid, tid):
        raise RuntimeError("broker down")

    monkeypatch.setattr("app.services.evaluation_dispatch._enqueue", boom)
    with session_factory() as db:
        response, _ = make_response(db, status=TranscriptionStatus.COMPLETED, transcript=TECHNICAL_TRANSCRIPT)
        rid = response.id
    assert evaluation_dispatch.dispatch_evaluation(rid, session_factory) is None
    with session_factory() as db:
        assert db.get(CandidateResponse, rid).evaluation_task_id is None  # can be dispatched again


def reload_status(factory, rid):
    with factory() as db:
        return db.get(CandidateResponse, rid).evaluation_status


# ---------------------------------------------------------------- Celery task (eager)
@pytest.fixture
def wired(monkeypatch, session_factory, settings):
    state = type("State", (), {})()
    state.provider = Scripted(json.dumps(valid_response()))
    monkeypatch.setattr("app.workers.evaluation_tasks.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.services.evaluation.engine.get_evaluation_provider", lambda s: state.provider)
    return state


def test_task_is_registered_under_the_documented_name():
    from app.workers.celery_app import celery_app

    assert "hireiq.evaluate_response" in celery_app.tasks


def test_task_evaluates_and_returns_no_candidate_data(wired, ready):
    rid, _ = ready()
    result = evaluate_response.apply(args=[str(rid)], task_id=TASK)
    assert result.result == {"status": "evaluated", "code": ""}


TIMEOUT = EvaluationProviderError("provider_timeout", "slow", retryable=True)


def test_task_retries_temporary_failures_until_success(wired, ready, session_factory):
    rid, _ = ready()
    wired.provider = Scripted(TIMEOUT, TIMEOUT, json.dumps(valid_response()))
    evaluate_response.apply(args=[str(rid)], task_id=TASK)
    assert wired.provider.calls == 3 and count(session_factory) == 1
    assert reload_status(session_factory, rid) == EvaluationStatus.COMPLETED


def test_task_stops_at_the_maximum_retries_and_stores_nothing(wired, ready, session_factory, monkeypatch):
    monkeypatch.setattr(evaluate_response, "max_retries", 2)
    rid, _ = ready()
    wired.provider = Scripted(TIMEOUT)
    evaluate_response.apply(args=[str(rid)], task_id=TASK)
    assert wired.provider.calls == 3  # first run + 2 retries, then it stops
    assert count(session_factory) == 0 and reload_status(session_factory, rid) == EvaluationStatus.FAILED


def test_permanent_failure_is_not_retried(wired, ready, session_factory):
    rid, _ = ready()
    wired.provider = Scripted(EvaluationProviderError("provider_auth", "bad key", retryable=False))
    assert evaluate_response.apply(args=[str(rid)], task_id=TASK).get() == {"status": "failed", "code": "provider_auth"}
    assert wired.provider.calls == 1


def test_invalid_output_is_retried_at_most_once(wired, ready, session_factory):
    rid, _ = ready()
    wired.provider = Scripted("not json")
    evaluate_response.apply(args=[str(rid)], task_id=TASK)
    assert wired.provider.calls == 2  # first run + ONE retry, although max_retries is higher
    assert count(session_factory) == 0 and reload_status(session_factory, rid) == EvaluationStatus.FAILED


def test_invalid_output_then_valid_output_succeeds(wired, ready, session_factory):
    rid, _ = ready()
    wired.provider = Scripted("not json", json.dumps(valid_response()))
    evaluate_response.apply(args=[str(rid)], task_id=TASK)
    assert count(session_factory) == 1


def test_duplicate_task_delivery_is_harmless(wired, ready, session_factory):
    rid, _ = ready()
    assert evaluate_response.apply(args=[str(rid)], task_id=TASK).result["status"] == "evaluated"
    assert evaluate_response.apply(args=[str(rid)], task_id=TASK).result == {"status": "skipped", "code": "not_owner"}
    assert wired.provider.calls == 1 and count(session_factory) == 1


# ---------------------------------------------------------------- session coordination
def test_session_stays_processing_while_other_answers_are_unfinished(session_factory, settings):
    with session_factory() as db:
        first, session = make_response(db, status=TranscriptionStatus.COMPLETED, transcript=TECHNICAL_TRANSCRIPT)
        session.status = SessionStatus.SUBMITTED
        second = CandidateResponse(session_id=session.id, question_id=session.interview.questions[1].id,
                                   transcription_status=TranscriptionStatus.PROCESSING, celery_task_id="t2")
        db.add(second)
        first.evaluation_task_id = TASK
        db.commit()
        rid, sid = first.id, session.id
    engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider())
    with session_factory() as db:
        assert db.get(InterviewSession, sid).status == SessionStatus.PROCESSING  # never EVALUATED here


def test_a_session_still_being_answered_is_not_advanced(session_factory, settings, ready):
    rid, sid = ready()
    with session_factory() as db:
        db.get(InterviewSession, sid).status = SessionStatus.IN_PROGRESS
        db.commit()
    engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider())
    with session_factory() as db:
        assert db.get(InterviewSession, sid).status == SessionStatus.IN_PROGRESS


# ---------------------------------------------------------------- stabilization (written; blocked here like the rest of this file)
def test_a_database_rejection_is_not_reported_as_a_duplicate(session_factory, settings, ready):
    """An IntegrityError other than 'row already exists' (here the 0..100 CHECK) must fail the answer, store nothing."""
    from app.services.evaluation.pipeline import evaluate_transcript

    rid, _ = ready()
    assert engine.claim(session_factory, rid, TASK)
    good = evaluate_transcript(
        provider=MockEvaluationProvider(), rubrics_dir=settings.rubrics_path, rubric_name="default",
        question_text="Explain processes and threads.", question_type="technical", rubric_key="technical",
        transcript=TECHNICAL_TRANSCRIPT,
    )
    bad = engine.ValidatedEvaluation(
        fields={**good.fields, "overall_score": 150.0}, breakdown=good.breakdown, parsed=good.parsed,
        provider=good.provider, model=good.model,
    )
    with pytest.raises(engine.EvaluationFailure) as info:
        engine._persist(session_factory, rid, TASK, bad)
    assert (info.value.code, info.value.retryable) == ("persistence_rejected", False)
    assert count(session_factory) == 0
    assert reload_status(session_factory, rid) == EvaluationStatus.PROCESSING  # NOT completed


def test_failed_evaluation_can_be_requeued_and_then_succeeds(session_factory, settings, ready, evaluation_enqueued):
    rid, sid = ready()
    error = EvaluationProviderError("provider_auth", "bad key", retryable=False)
    assert engine.run(session_factory, rid, TASK, settings, Scripted(error)).status == "failed"
    with session_factory() as db:
        assert db.get(InterviewSession, sid).status == SessionStatus.FAILED
    new_task = evaluation_dispatch.requeue_failed_evaluation(rid, session_factory)
    assert new_task and new_task != TASK and evaluation_enqueued[-1] == (rid, new_task)
    with session_factory() as db:
        assert db.get(InterviewSession, sid).status == SessionStatus.PROCESSING
    assert engine.run(session_factory, rid, new_task, settings, MockEvaluationProvider()).status == "evaluated"
    assert count(session_factory) == 1


def test_requeue_does_nothing_for_evaluated_or_not_failed_answers(session_factory, settings, ready, evaluation_enqueued):
    rid, _ = ready()
    assert evaluation_dispatch.requeue_failed_evaluation(rid, session_factory) is None  # still processing/pending
    engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider())
    assert evaluation_dispatch.requeue_failed_evaluation(rid, session_factory) is None  # completed
    assert count(session_factory) == 1 and evaluation_enqueued == []


def test_requeue_does_not_touch_a_failed_transcription(session_factory, evaluation_enqueued):
    with session_factory() as db:
        response, _ = make_response(db, status=TranscriptionStatus.FAILED)
        response.evaluation_status = EvaluationStatus.FAILED
        db.commit()
        rid = response.id
    assert evaluation_dispatch.requeue_failed_evaluation(rid, session_factory) is None
    assert evaluation_enqueued == []


# ---------------------------------------------------------------- Day 5: NLP enrichment persistence (written; blocked here)
FAKE_NLP = {"schema_version": 1, "status": "completed", "word_count": 5, "keywords": [{"text": "thread", "count": 1}],
            "entities": [], "sentiment": None, "confidence": None, "errors": {}, "models": {}}


def test_enrichment_is_persisted_with_the_evaluation_in_the_same_row(session_factory, settings, ready, monkeypatch):
    monkeypatch.setattr("app.services.nlp.service.enrich", lambda *a, **k: dict(FAKE_NLP))
    rid, _ = ready()
    assert engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider()).status == "evaluated"
    with session_factory() as db:
        rows = db.scalars(sa.select(Evaluation).where(Evaluation.response_id == rid)).all()
        assert len(rows) == 1 and rows[0].nlp_enrichment == FAKE_NLP


def test_nlp_failure_does_not_destroy_the_llm_evaluation(session_factory, settings, ready, monkeypatch):
    failed = {"schema_version": 1, "status": "failed", "word_count": 3, "errors": {"spacy": "spacy_model_missing"}}
    monkeypatch.setattr("app.services.nlp.service.enrich", lambda *a, **k: failed)
    rid, _ = ready()
    assert engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider()).status == "evaluated"
    with session_factory() as db:
        row = db.scalar(sa.select(Evaluation).where(Evaluation.response_id == rid))
        assert row.nlp_enrichment == failed and 0 <= row.overall_score <= 100 and row.recommendation


def test_a_crash_in_nlp_still_stores_the_evaluation(session_factory, settings, ready, monkeypatch):
    def explode(*a, **k):
        raise MemoryError("boom")

    monkeypatch.setattr("app.services.nlp.service.enrich", explode)
    rid, _ = ready()
    assert engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider()).status == "evaluated"
    with session_factory() as db:
        assert db.scalar(sa.select(Evaluation).where(Evaluation.response_id == rid)).nlp_enrichment["status"] == "failed"


def test_nlp_does_not_change_score_or_recommendation(session_factory, ready, monkeypatch):
    results = {}
    for enabled in ("true", "false"):
        monkeypatch.setenv("EVALUATION_PROVIDER", "mock")
        monkeypatch.setenv("NLP_ENABLED", enabled)
        get_settings.cache_clear()
        rid, _ = ready()
        engine.run(session_factory, rid, TASK, get_settings(), MockEvaluationProvider())
        with session_factory() as db:
            row = db.scalar(sa.select(Evaluation).where(Evaluation.response_id == rid))
            results[enabled] = (row.overall_score, row.recommendation, row.criteria_scores, row.nlp_enrichment is None)
    assert results["true"][:3] == results["false"][:3]
    assert results["true"][3] is False and results["false"][3] is True  # disabled -> column stays NULL


def test_duplicate_delivery_creates_no_second_enriched_row(session_factory, settings, ready, monkeypatch):
    monkeypatch.setattr("app.services.nlp.service.enrich", lambda *a, **k: dict(FAKE_NLP))
    rid, _ = ready()
    engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider())
    assert engine.run(session_factory, rid, TASK, settings, MockEvaluationProvider()).code == "not_owner"
    assert count(session_factory) == 1
