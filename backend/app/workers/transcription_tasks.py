"""Celery task that transcribes one uploaded answer."""

import logging
import uuid

from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_ready

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services import evaluation_dispatch, transcription_service
from app.services.audio_intake import purge_stale_audio
from app.services.transcription.base import TranscriptionError
from app.services.transcription.factory import get_provider
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_settings = get_settings()


@celery_app.task(
    bind=True,
    name="hireiq.transcribe_response",
    max_retries=_settings.transcription_max_retries,
    soft_time_limit=600,
    time_limit=660,
)
def transcribe_response(self, response_id: str) -> dict[str, str]:
    """Transcribe the stored audio of one CandidateResponse.

    Only the response id travels through Redis. The result dict holds a status and an error code,
    never any transcript text. Safe to run twice: the database claim lets only the task whose id was
    stored at dispatch time do the work (see transcription_service.claim).
    """
    settings = get_settings()
    rid = uuid.UUID(response_id)
    task_id = str(self.request.id)
    factory = get_session_factory()

    try:
        provider = get_provider(settings)
        outcome = transcription_service.run(factory, rid, task_id, settings, provider)
        if outcome.status in ("completed", "failed"):  # Day 4: hand over to evaluation (never raises)
            evaluation_dispatch.after_transcription(rid, factory)
        return outcome.as_dict()
    except SoftTimeLimitExceeded:
        error = TranscriptionError("task_timeout", "The task ran too long.", retryable=True)
    except TranscriptionError as exc:
        error = exc
    except Exception as exc:  # noqa: BLE001 - a bug must not loop forever or lose the audio
        logger.error("Unexpected error in transcription task response_id=%s error=%s", rid, type(exc).__name__)
        transcription_service.mark_failed(factory, rid, task_id, "internal_error")
        evaluation_dispatch.after_transcription(rid, factory)
        return {"status": "failed", "code": "internal_error"}

    if error.retryable and self.request.retries < self.max_retries:
        delay = transcription_service.backoff_seconds(self.request.retries, error.retry_after)
        logger.warning(
            "Retrying response_id=%s in %ss (retry %d of %d, code=%s)",
            rid, delay, self.request.retries + 1, self.max_retries, error.code,
        )
        raise self.retry(exc=error, countdown=delay)

    # Retries used up, or a permanent configuration problem. The audio is KEPT (retention policy)
    # so that the recording can be re-queued after the cause is fixed.
    transcription_service.mark_failed(factory, rid, task_id, error.code)
    evaluation_dispatch.after_transcription(rid, factory)  # refreshes the session status; no evaluation is started
    return {"status": "failed", "code": error.code}


@worker_ready.connect
def _purge_leftovers_on_worker_start(**_: object) -> None:
    """Retention policy: remove audio and scratch folders older than AUDIO_STALE_AFTER_HOURS."""
    settings = get_settings()
    try:
        purge_stale_audio(settings.audio_temp_dir, settings.audio_stale_after_hours * 3600)
    except OSError as exc:
        logger.warning("Stale audio purge failed: %s", type(exc).__name__)
