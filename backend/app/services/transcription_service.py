"""One transcription attempt, with database ownership checks.

Safety rules:
- A worker may only process a response whose `celery_task_id` equals ITS task id and whose status is
  pending/processing (the "claim"). Two tasks can therefore never work on the same recording.
- Every result write is a guarded UPDATE with the same ownership condition. If another task took over
  in the meantime, our result is discarded and OUR code does not delete the audio.
- Raw audio is deleted only AFTER the transcript is committed, and only by the owner.
- Logs contain ids, codes and lengths. Never transcript text, names or emails.
"""

import logging
import shutil
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import CandidateResponse, TranscriptionStatus
from app.services import audio_intake, audio_processing
from app.services.audio_processing import AudioProcessingError
from app.services.transcription.base import TranscriptionError, TranscriptionProvider, TranscriptionResult

logger = logging.getLogger(__name__)

OPEN_STATES = (TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING)


@dataclass(frozen=True)
class Outcome:
    status: str  # "completed" | "failed" | "skipped"
    code: str | None = None

    def as_dict(self) -> dict[str, str]:
        """Safe to store in the Celery result backend: no candidate data."""
        return {"status": self.status, "code": self.code or ""}


def backoff_seconds(retries_so_far: int, retry_after: float | None = None) -> int:
    """5s, 10s, 20s... capped at 120s; never shorter than the provider's Retry-After."""
    base = min(5 * (2 ** retries_so_far), 120)
    return int(max(base, retry_after or 0))


def _owned_where(response_id: uuid.UUID, task_id: str, states: tuple[TranscriptionStatus, ...]):
    return (
        CandidateResponse.id == response_id,
        CandidateResponse.celery_task_id == task_id,
        CandidateResponse.transcription_status.in_(states),
    )


def claim(db: Session, response_id: uuid.UUID, task_id: str) -> bool:
    """Mark the response as 'processing' for THIS task. False means: not ours / already finished."""
    result = db.execute(
        sa.update(CandidateResponse)
        .where(*_owned_where(response_id, task_id, OPEN_STATES))
        .values(
            transcription_status=TranscriptionStatus.PROCESSING,
            transcription_started_at=sa.func.now(),
            transcription_attempts=CandidateResponse.transcription_attempts + 1,
            transcription_error=None,
        )
    )
    db.commit()
    return result.rowcount == 1


def _finish_completed(
    db: Session, response_id: uuid.UUID, task_id: str, result: TranscriptionResult, duration: float, no_speech: bool
) -> bool:
    outcome = db.execute(
        sa.update(CandidateResponse)
        .where(*_owned_where(response_id, task_id, (TranscriptionStatus.PROCESSING,)))
        .values(
            transcription_status=TranscriptionStatus.COMPLETED,
            transcript=result.text,
            transcript_segments=result.segments or None,
            transcript_language=result.language,
            transcription_provider=(result.provider or None),
            audio_duration_seconds=duration,
            no_speech_detected=no_speech,
            transcription_completed_at=sa.func.now(),
            transcription_error=None,
        )
    )
    db.commit()
    return outcome.rowcount == 1


def mark_failed(factory: sessionmaker, response_id: uuid.UUID, task_id: str, code: str) -> bool:
    """Record a failure (guarded by ownership). Returns True if this task still owned the response."""
    with factory() as db:
        outcome = db.execute(
            sa.update(CandidateResponse)
            .where(*_owned_where(response_id, task_id, OPEN_STATES))
            .values(
                transcription_status=TranscriptionStatus.FAILED,
                transcription_error=code[:100],
                transcription_completed_at=sa.func.now(),
            )
        )
        db.commit()
        return outcome.rowcount == 1


def _fail(factory: sessionmaker, settings: Settings, response_id: uuid.UUID, task_id: str, code: str, delete_audio: bool) -> Outcome:
    owned = mark_failed(factory, response_id, task_id, code)
    if owned and delete_audio:
        audio_intake.delete_audio(response_id, settings.audio_temp_dir)
    logger.warning("Transcription failed response_id=%s code=%s audio_deleted=%s", response_id, code, owned and delete_audio)
    return Outcome("failed", code)


def run(
    factory: sessionmaker,
    response_id: uuid.UUID,
    task_id: str,
    settings: Settings,
    provider: TranscriptionProvider,
) -> Outcome:
    """Process one recording. Raises TranscriptionError ONLY for retryable provider failures."""
    with factory() as db:
        if not claim(db, response_id, task_id):
            logger.info("Skipping response_id=%s: not owned by task %s or already finished", response_id, task_id)
            return Outcome("skipped", "not_owner")

    source = audio_intake.find_audio_path(response_id, settings.audio_temp_dir)
    if source is None:
        return _fail(factory, settings, response_id, task_id, "audio_missing", delete_audio=False)

    work_dir = audio_intake.make_work_dir(settings.audio_temp_dir, response_id)
    try:
        processed = audio_processing.prepare_for_transcription(
            source,
            work_dir,
            max_duration_seconds=settings.audio_max_duration_seconds,
            min_duration_ms=settings.audio_min_duration_ms,
            target_sample_rate=settings.audio_target_sample_rate,
        )
        if processed.is_silent or processed.path is None:
            result = TranscriptionResult(text="", duration_seconds=processed.duration_seconds, provider="none")
        else:
            result = provider.transcribe(processed.path, language=settings.transcription_language)
    except AudioProcessingError as exc:
        return _fail(factory, settings, response_id, task_id, exc.code, delete_audio=exc.delete_audio)
    except TranscriptionError as exc:
        if exc.retryable:
            raise  # the Celery task decides whether to retry
        return _fail(factory, settings, response_id, task_id, exc.code, delete_audio=False)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)  # intermediate files never outlive the attempt

    no_speech = processed.is_silent or not result.has_speech
    with factory() as db:
        owned = _finish_completed(db, response_id, task_id, result, processed.duration_seconds, no_speech)
    if not owned:
        logger.warning("Result for response_id=%s discarded: another task took over", response_id)
        return Outcome("skipped", "ownership_lost")

    audio_intake.delete_audio(response_id, settings.audio_temp_dir)  # only after the transcript is stored
    logger.info(
        "Transcription completed response_id=%s provider=%s chars=%d no_speech=%s",
        response_id, result.provider, len(result.text), no_speech,
    )
    return Outcome("completed")
