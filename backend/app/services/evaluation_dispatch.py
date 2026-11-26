"""Connects a finished transcription to the Celery evaluation task (Day 4, Phase 3).

`after_transcription` is called by the transcription task when it ends. It never raises: a broker or
database problem must not affect the transcription result; the answer simply stays 'pending' for evaluation
and can be dispatched again later.

Decision table (transcription_status of the answer):
  pending / processing  -> do nothing yet (evaluation never starts before transcription completes)
  failed                -> no evaluation; refresh the session status
  completed + no speech -> evaluation SKIPPED ('no_speech'); no model call; refresh the session status
  completed + no text   -> evaluation FAILED ('transcript_missing'); refresh the session status
  completed + text      -> claim once (task id stored in the database) and enqueue; duplicates do nothing
"""

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.database import get_session_factory
from app.models import CandidateResponse, Evaluation, EvaluationStatus, TranscriptionStatus
from app.services.evaluation import coordination

logger = logging.getLogger(__name__)


def _enqueue(response_id: uuid.UUID, task_id: str) -> None:
    from app.workers.evaluation_tasks import evaluate_response  # lazy: avoids circular imports

    evaluate_response.apply_async(args=[str(response_id)], task_id=task_id)


def _set_terminal(factory: sessionmaker, response_id: uuid.UUID, status: EvaluationStatus, code: str) -> None:
    with factory() as db:
        db.execute(
            sa.update(CandidateResponse)
            .where(CandidateResponse.id == response_id, CandidateResponse.evaluation_status == EvaluationStatus.PENDING,
                   CandidateResponse.evaluation_task_id.is_(None))
            .values(evaluation_status=status, evaluation_error=code)
        )
        db.commit()


def dispatch_evaluation(response_id: uuid.UUID, factory: sessionmaker | None = None) -> str | None:
    """Queue the evaluation once. Returns the task id (new or existing), or None when nothing was queued."""
    try:
        factory = factory or get_session_factory()
        with factory() as db:
            row = db.execute(
                sa.select(
                    CandidateResponse.session_id, CandidateResponse.transcription_status,
                    CandidateResponse.no_speech_detected,
                    sa.func.coalesce(sa.func.length(sa.func.trim(CandidateResponse.transcript)), 0),
                    CandidateResponse.evaluation_status, CandidateResponse.evaluation_task_id,
                ).where(CandidateResponse.id == response_id)
            ).one_or_none()
        if row is None:
            return None
        session_id, t_status, no_speech, text_length, e_status, existing = row

        if t_status in (TranscriptionStatus.PENDING, TranscriptionStatus.PROCESSING):
            logger.info("Evaluation waits for transcription response_id=%s", response_id)
            return None
        if t_status == TranscriptionStatus.FAILED:
            coordination.refresh_session_status(factory, session_id)
            return None
        if e_status != EvaluationStatus.PENDING or existing:
            logger.info("Evaluation already dispatched response_id=%s", response_id)  # duplicate delivery
            return existing
        if no_speech:
            _set_terminal(factory, response_id, EvaluationStatus.SKIPPED, "no_speech")
            coordination.refresh_session_status(factory, session_id)
            return None
        if text_length <= 0:
            _set_terminal(factory, response_id, EvaluationStatus.FAILED, "transcript_missing")
            coordination.refresh_session_status(factory, session_id)
            return None

        task_id = str(uuid.uuid4())
        with factory() as db:
            claimed = db.execute(
                sa.update(CandidateResponse)
                .where(
                    CandidateResponse.id == response_id,
                    CandidateResponse.transcription_status == TranscriptionStatus.COMPLETED,
                    CandidateResponse.evaluation_status == EvaluationStatus.PENDING,
                    CandidateResponse.evaluation_task_id.is_(None),
                )
                .values(evaluation_task_id=task_id)
            )
            db.commit()
            if claimed.rowcount != 1:
                return db.scalar(sa.select(CandidateResponse.evaluation_task_id).where(CandidateResponse.id == response_id))
        try:
            _enqueue(response_id, task_id)
        except Exception as exc:  # noqa: BLE001 - broker down
            logger.error("Could not queue evaluation response_id=%s error=%s", response_id, type(exc).__name__)
            with factory() as db:  # undo the id so it can be dispatched again
                db.execute(
                    sa.update(CandidateResponse)
                    .where(CandidateResponse.id == response_id, CandidateResponse.evaluation_task_id == task_id)
                    .values(evaluation_task_id=None)
                )
                db.commit()
            return None
        logger.info("Queued evaluation response_id=%s task_id=%s", response_id, task_id)
        return task_id
    except Exception as exc:  # noqa: BLE001
        logger.error("Evaluation dispatch failed response_id=%s error=%s", response_id, type(exc).__name__)
        return None


def after_transcription(response_id: uuid.UUID, factory: sessionmaker | None = None) -> None:
    """Hook for the end of the transcription task (completed, no speech, or permanently failed)."""
    dispatch_evaluation(response_id, factory)


def requeue_failed_evaluation(response_id: uuid.UUID, factory: sessionmaker | None = None) -> str | None:
    """Give a FAILED evaluation another chance (after the cause was fixed, e.g. an API key or a rubric file).

    Safe because a failed evaluation never has an Evaluation row. The guarded UPDATE only touches an answer that is
    `failed` with a COMPLETED transcription; it resets the claim and then goes through the normal dispatch, so all
    duplicate protection still applies. Returns the new task id, or None if nothing was re-queued. No API route
    calls this yet: it is for a shell/admin task or a later approved endpoint.
    """
    try:
        factory = factory or get_session_factory()
        with factory() as db:
            reset = db.execute(
                sa.update(CandidateResponse)
                .where(
                    CandidateResponse.id == response_id,
                    CandidateResponse.evaluation_status == EvaluationStatus.FAILED,
                    CandidateResponse.transcription_status == TranscriptionStatus.COMPLETED,
                    ~sa.exists().where(Evaluation.response_id == response_id),
                )
                .values(evaluation_status=EvaluationStatus.PENDING, evaluation_task_id=None, evaluation_error=None)
            )
            session_id = db.scalar(sa.select(CandidateResponse.session_id).where(CandidateResponse.id == response_id))
            db.commit()
        if reset.rowcount != 1:
            logger.info("Nothing to re-queue for response_id=%s", response_id)
            return None
        if session_id is not None:
            coordination.refresh_session_status(factory, session_id)  # FAILED session -> PROCESSING again
        return dispatch_evaluation(response_id, factory)
    except Exception as exc:  # noqa: BLE001
        logger.error("Evaluation re-queue failed response_id=%s error=%s", response_id, type(exc).__name__)
        return None
