"""Connects a stored upload to the Celery transcription task.

Called by the API after the answer and its audio were saved. It never raises: if the broker is down
the upload still succeeds, the recording stays 'pending' without a task id, and the retry endpoint
(or a later manual re-queue) can start it.
"""

import logging
import uuid

import sqlalchemy as sa

from app.core.database import get_session_factory
from app.models import CandidateResponse, TranscriptionStatus

logger = logging.getLogger(__name__)


def _enqueue(response_id: uuid.UUID, task_id: str) -> None:
    # Imported here: avoids a circular import and keeps API start-up independent of the worker module.
    from app.workers.transcription_tasks import transcribe_response

    transcribe_response.apply_async(args=[str(response_id)], task_id=task_id)


def dispatch_transcription(response_id: uuid.UUID) -> str | None:
    """Queue transcription once. Returns the task id (new or already existing), or None on failure."""
    try:
        factory = get_session_factory()
        task_id = str(uuid.uuid4())
        with factory() as db:
            claimed = db.execute(
                sa.update(CandidateResponse)
                .where(
                    CandidateResponse.id == response_id,
                    CandidateResponse.transcription_status == TranscriptionStatus.PENDING,
                    CandidateResponse.celery_task_id.is_(None),
                )
                .values(celery_task_id=task_id)
            )
            db.commit()
            if claimed.rowcount != 1:
                # Duplicate dispatch: a task already exists (or the response is finished). Do nothing.
                existing = db.scalar(sa.select(CandidateResponse.celery_task_id).where(CandidateResponse.id == response_id))
                logger.info("Transcription already dispatched for response_id=%s", response_id)
                return existing

        try:
            _enqueue(response_id, task_id)
        except Exception as exc:  # noqa: BLE001 - broker down etc.
            logger.error("Could not queue transcription response_id=%s error=%s", response_id, type(exc).__name__)
            with factory() as db:  # undo the id so the recording can be dispatched again later
                db.execute(
                    sa.update(CandidateResponse)
                    .where(CandidateResponse.id == response_id, CandidateResponse.celery_task_id == task_id)
                    .values(celery_task_id=None)
                )
                db.commit()
            return None
        logger.info("Queued transcription response_id=%s task_id=%s", response_id, task_id)
        return task_id
    except Exception as exc:  # noqa: BLE001 - the upload itself must never fail because of this
        logger.error("Transcription dispatch failed response_id=%s error=%s", response_id, type(exc).__name__)
        return None
