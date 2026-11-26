"""One transcription attempt: claim, process, store, delete. REAL database code (SQLite stand-in) and
REAL PyDub processing of generated WAV files; the transcription provider is a MOCKED test double."""

import logging
import types

import pytest

from app.core.config import get_settings
from app.models import TranscriptionStatus
from app.services import audio_intake
from app.services import transcription_service as svc
from app.services.transcription.base import TranscriptionError, TranscriptionProvider, TranscriptionResult
from tests.builders import make_response, reload
from tests.helpers_audio import silent_wav_bytes, wav_bytes

GOOD = TranscriptionResult(
    text="B-tree indexes speed up lookups.", language="en", duration_seconds=1.9,
    segments=[{"start": 0.0, "end": 1.9, "text": "B-tree indexes speed up lookups."}], provider="fake", model="m",
)


class FakeProvider(TranscriptionProvider):
    """MOCK provider: plays back a list of results/exceptions (the last one repeats)."""

    name = "fake"

    def __init__(self, *steps, on_call=None):
        self.steps, self.calls, self.paths, self.on_call = list(steps), 0, [], on_call

    def transcribe(self, audio_path, *, language=None):
        self.calls += 1
        self.paths.append(audio_path)
        assert audio_path.exists(), "the prepared file must exist while the provider runs"
        if self.on_call:
            self.on_call()
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def ctx(session_factory, audio_dir):
    settings = get_settings()

    def create(data=None, **fields):
        with session_factory() as db:
            response, _ = make_response(db, **fields)
            rid = response.id
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / f"{rid}.wav").write_bytes(wav_bytes(1.2, 44100, 2) if data is None else data)
        return rid

    return types.SimpleNamespace(settings=settings, factory=session_factory, create=create, dir=audio_dir)


def run(ctx, rid, provider, task_id="task-1"):
    return svc.run(ctx.factory, rid, task_id, ctx.settings, provider)


def row(ctx, rid):
    with ctx.factory() as db:
        return reload(db, rid)


def work_leftovers(ctx):
    work = ctx.dir / ".work"
    return list(work.iterdir()) if work.exists() else []


def test_success_stores_transcript_and_deletes_audio(ctx):
    rid, provider = ctx.create(), FakeProvider(GOOD)
    outcome = run(ctx, rid, provider)
    r = row(ctx, rid)
    assert outcome.status == "completed"
    assert r.transcription_status == TranscriptionStatus.COMPLETED
    assert r.transcript == GOOD.text and r.transcript_language == "en"
    assert r.transcript_segments == GOOD.segments and r.transcription_provider == "fake"
    assert r.audio_duration_seconds == pytest.approx(1.2, abs=0.1)  # measured from the real file
    assert r.transcription_attempts == 1 and r.transcription_error is None and not r.no_speech_detected
    assert r.transcription_started_at is not None and r.transcription_completed_at is not None
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is None, "raw audio must be deleted"
    assert work_leftovers(ctx) == [] and not provider.paths[0].exists()


def test_provider_receives_the_prepared_mono_16k_file(ctx):
    rid, provider = ctx.create(), FakeProvider(GOOD)
    run(ctx, rid, provider)
    assert provider.paths[0].name == "prepared.wav"


def test_no_recognisable_speech_is_completed_with_a_flag(ctx):
    rid = ctx.create()
    run(ctx, rid, FakeProvider(TranscriptionResult(text="", language="en", provider="fake")))
    r = row(ctx, rid)
    assert r.transcription_status == TranscriptionStatus.COMPLETED and r.transcript == "" and r.no_speech_detected


def test_silent_recording_skips_the_provider_entirely(ctx):
    rid, provider = ctx.create(silent_wav_bytes(1.0)), FakeProvider(GOOD)
    run(ctx, rid, provider)
    r = row(ctx, rid)
    assert provider.calls == 0
    assert r.transcription_status == TranscriptionStatus.COMPLETED and r.no_speech_detected and r.transcription_provider == "none"
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is None


@pytest.mark.parametrize("data, code", [
    (b"this is plain text, not audio", "audio_unsupported"),
    (wav_bytes(0.05, 16000, 1), "audio_too_short"),
])
def test_bad_audio_fails_permanently_and_is_deleted(ctx, data, code):
    rid, provider = ctx.create(data), FakeProvider(GOOD)
    outcome = run(ctx, rid, provider)
    r = row(ctx, rid)
    assert (outcome.status, outcome.code) == ("failed", code)
    assert r.transcription_status == TranscriptionStatus.FAILED and r.transcription_error == code
    assert provider.calls == 0
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is None
    assert work_leftovers(ctx) == []


def test_retryable_provider_error_is_raised_and_keeps_everything_for_the_retry(ctx):
    rid = ctx.create()
    with pytest.raises(TranscriptionError) as exc:
        run(ctx, rid, FakeProvider(TranscriptionError("provider_timeout", "slow", retryable=True)))
    r = row(ctx, rid)
    assert exc.value.retryable
    assert r.transcription_status == TranscriptionStatus.PROCESSING  # the task will retry; not failed yet
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is not None
    assert work_leftovers(ctx) == []


def test_the_same_task_can_resume_after_a_retry_or_a_worker_crash(ctx):
    rid = ctx.create()
    with pytest.raises(TranscriptionError):
        run(ctx, rid, FakeProvider(TranscriptionError("rate_limited", "x", retryable=True)))
    outcome = run(ctx, rid, FakeProvider(GOOD))  # redelivery with the SAME task id
    r = row(ctx, rid)
    assert outcome.status == "completed" and r.transcription_attempts == 2


def test_permanent_provider_error_fails_but_keeps_audio_for_recovery(ctx):
    rid = ctx.create()
    outcome = run(ctx, rid, FakeProvider(TranscriptionError("provider_auth", "bad key", retryable=False)))
    assert (outcome.status, outcome.code) == ("failed", "provider_auth")
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is not None


def test_missing_audio_file_fails_cleanly(ctx):
    rid = ctx.create()
    audio_intake.delete_audio(rid, str(ctx.dir))
    outcome = run(ctx, rid, FakeProvider(GOOD))
    assert (outcome.status, outcome.code) == ("failed", "audio_missing")


def test_a_task_that_does_not_own_the_recording_does_nothing(ctx):
    rid, provider = ctx.create(task_id="task-1"), FakeProvider(GOOD)
    outcome = run(ctx, rid, provider, task_id="some-other-task")
    r = row(ctx, rid)
    assert outcome.status == "skipped" and provider.calls == 0
    assert r.transcription_status == TranscriptionStatus.PENDING and r.transcription_attempts == 0
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is not None


@pytest.mark.parametrize("status", [TranscriptionStatus.COMPLETED, TranscriptionStatus.FAILED])
def test_finished_recordings_are_never_processed_again(ctx, status):
    rid, provider = ctx.create(status=status), FakeProvider(GOOD)
    assert run(ctx, rid, provider).status == "skipped" and provider.calls == 0


def test_result_is_discarded_and_audio_kept_if_another_task_took_over(ctx):
    rid = ctx.create()

    def steal():  # simulates the retry endpoint handing the recording to a new task mid-flight
        from sqlalchemy import update
        from app.models import CandidateResponse
        with ctx.factory() as db:
            db.execute(update(CandidateResponse).where(CandidateResponse.id == rid).values(celery_task_id="new-task"))
            db.commit()

    outcome = run(ctx, rid, FakeProvider(GOOD, on_call=steal))
    r = row(ctx, rid)
    assert (outcome.status, outcome.code) == ("skipped", "ownership_lost")
    assert r.transcript is None and r.celery_task_id == "new-task"
    assert audio_intake.find_audio_path(rid, str(ctx.dir)) is not None, "the new owner still needs the audio"


def test_mark_failed_requires_ownership(ctx):
    rid = ctx.create(task_id="task-1")
    assert svc.mark_failed(ctx.factory, rid, "intruder", "internal_error") is False
    assert row(ctx, rid).transcription_status == TranscriptionStatus.PENDING
    assert svc.mark_failed(ctx.factory, rid, "task-1", "internal_error") is True
    assert row(ctx, rid).transcription_error == "internal_error"


def test_backoff_grows_is_capped_and_respects_retry_after():
    assert [svc.backoff_seconds(n) for n in (0, 1, 2, 10)] == [5, 10, 20, 120]
    assert svc.backoff_seconds(0, retry_after=300) == 300


def test_logs_never_contain_transcript_text(ctx, caplog):
    rid = ctx.create()
    with caplog.at_level(logging.DEBUG):
        run(ctx, rid, FakeProvider(GOOD))
    assert "B-tree" not in caplog.text and "lookups" not in caplog.text
    assert str(rid) in caplog.text
