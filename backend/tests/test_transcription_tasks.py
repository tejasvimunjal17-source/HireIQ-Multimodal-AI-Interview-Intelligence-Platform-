"""The Celery task, run in-process with Task.apply() (eager). This exercises the task code, retry
logic and database updates, but NOT a real broker or worker: the real-worker check is the CI smoke test."""

import uuid

import pytest

from app.core.config import get_settings
from app.models import TranscriptionStatus
from app.services import audio_intake
from app.services.transcription.base import TranscriptionError
from app.workers.celery_app import celery_app
from app.workers.transcription_tasks import transcribe_response
from tests.builders import make_response, reload
from tests.test_transcription_service import GOOD, FakeProvider
from tests.helpers_audio import wav_bytes

TIMEOUT = TranscriptionError("provider_timeout", "slow", retryable=True)


@pytest.fixture
def wired(monkeypatch, session_factory, audio_dir):
    state = type("State", (), {})()
    state.provider = FakeProvider(GOOD)
    monkeypatch.setattr("app.workers.transcription_tasks.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.workers.transcription_tasks.get_provider", lambda settings: state.provider)

    def create(task_id="task-1"):
        with session_factory() as db:
            response, _ = make_response(db, task_id=task_id)
            rid = response.id
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / f"{rid}.wav").write_bytes(wav_bytes(1.0, 16000, 1))
        return rid

    state.create, state.factory, state.dir = create, session_factory, audio_dir
    return state


def apply(rid, task_id="task-1"):
    return transcribe_response.apply(args=[str(rid)], task_id=task_id)


def row(state, rid):
    with state.factory() as db:
        return reload(db, rid)


def test_task_is_registered_with_safe_settings():
    celery_app.loader.import_default_modules()
    assert "hireiq.transcribe_response" in celery_app.tasks
    assert transcribe_response.max_retries == get_settings().transcription_max_retries
    assert transcribe_response.soft_time_limit < transcribe_response.time_limit
    assert celery_app.conf.task_acks_late and celery_app.conf.task_reject_on_worker_lost


def test_success_updates_the_database_and_returns_no_candidate_data(wired):
    rid = wired.create()
    result = apply(rid).get()
    assert result == {"status": "completed", "code": ""}  # nothing sensitive goes to the result backend
    r = row(wired, rid)
    assert r.transcription_status == TranscriptionStatus.COMPLETED and r.transcript == GOOD.text
    assert audio_intake.find_audio_path(rid, str(wired.dir)) is None


def test_temporary_failures_are_retried_until_success(wired):
    wired.provider = FakeProvider(TIMEOUT, TIMEOUT, GOOD)
    rid = wired.create()
    apply(rid)
    r = row(wired, rid)
    assert r.transcription_status == TranscriptionStatus.COMPLETED
    assert r.transcription_attempts == 3 and wired.provider.calls == 3


def test_retries_stop_at_the_maximum_and_audio_is_kept(wired, monkeypatch):
    monkeypatch.setattr(transcribe_response, "max_retries", 2)
    wired.provider = FakeProvider(TIMEOUT)  # always fails
    rid = wired.create()
    apply(rid)
    r = row(wired, rid)
    assert wired.provider.calls == 3  # first run + 2 retries
    assert r.transcription_status == TranscriptionStatus.FAILED and r.transcription_error == "provider_timeout"
    assert audio_intake.find_audio_path(rid, str(wired.dir)) is not None, "kept for manual recovery"


def test_permanent_failure_is_not_retried(wired):
    wired.provider = FakeProvider(TranscriptionError("provider_auth", "bad key", retryable=False))
    rid = wired.create()
    assert apply(rid).get() == {"status": "failed", "code": "provider_auth"}
    assert wired.provider.calls == 1


def test_unexpected_exception_marks_failed_without_looping(wired):
    wired.provider = FakeProvider(RuntimeError("bug"))
    rid = wired.create()
    assert apply(rid).get() == {"status": "failed", "code": "internal_error"}
    assert row(wired, rid).transcription_status == TranscriptionStatus.FAILED
    assert audio_intake.find_audio_path(rid, str(wired.dir)) is not None


def test_a_duplicate_task_with_another_id_is_skipped(wired):
    rid = wired.create(task_id="task-1")
    assert apply(rid, task_id="duplicate-task").get() == {"status": "skipped", "code": "not_owner"}
    assert wired.provider.calls == 0
    assert row(wired, rid).transcription_status == TranscriptionStatus.PENDING


def test_running_the_same_task_twice_processes_only_once(wired):
    rid = wired.create()
    apply(rid)
    assert apply(rid).get() == {"status": "skipped", "code": "not_owner"}
    assert wired.provider.calls == 1


def test_provider_configuration_error_fails_the_response(wired, monkeypatch):
    def broken(settings):
        raise TranscriptionError("provider_not_configured", "no key", retryable=False)

    monkeypatch.setattr("app.workers.transcription_tasks.get_provider", broken)
    rid = wired.create()
    assert apply(rid).get() == {"status": "failed", "code": "provider_not_configured"}
    assert row(wired, rid).transcription_status == TranscriptionStatus.FAILED
