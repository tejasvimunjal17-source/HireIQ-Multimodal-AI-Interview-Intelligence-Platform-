"""Evaluation engine (Day 4, Phase 3): evaluates ONE eligible answer end to end.

    claim (DB) -> load question + rubric name (DB) -> pipeline.evaluate_transcript (rubric, prompt, provider,
    schema + evidence validation, weighted score) -> persist Evaluation + status in ONE transaction -> refresh
    the session status.

The database-free core and the failure codes are documented in pipeline.py.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models import (
    CandidateResponse, Evaluation, EvaluationStatus, Interview, Question, Recommendation, TranscriptionStatus,
)
from app.services.evaluation import coordination
from app.services.nlp import enrich_fields
from app.services.evaluation.pipeline import (  # noqa: F401  (re-exported: the engine's public surface)
    EvaluationFailure, ValidatedEvaluation, backoff_seconds, evaluate_transcript,
)
from app.services.evaluation.providers.base import EvaluationProvider, EvaluationProviderError
from app.services.evaluation.providers.factory import get_evaluation_provider

logger = logging.getLogger(__name__)

OPEN_STATES = (EvaluationStatus.PENDING, EvaluationStatus.PROCESSING)


@dataclass(frozen=True)
class Outcome:
    status: str  # "evaluated" | "failed" | "skipped"
    code: str | None = None

    def as_dict(self) -> dict[str, str]:
        """Safe for the Celery result backend: no candidate data."""
        return {"status": self.status, "code": self.code or ""}


def _owned(response_id: uuid.UUID, task_id: str, states: tuple[EvaluationStatus, ...] = OPEN_STATES):
    return (
        CandidateResponse.id == response_id,
        CandidateResponse.evaluation_task_id == task_id,
        CandidateResponse.evaluation_status.in_(states),
    )


def claim(factory: sessionmaker, response_id: uuid.UUID, task_id: str) -> bool:
    """Mark the answer 'processing' for THIS task. Only the task whose id was stored at dispatch can claim it,
    and only once the transcription is COMPLETED. False = not ours / already finished (duplicate delivery)."""
    with factory() as db:
        result = db.execute(
            sa.update(CandidateResponse)
            .where(*_owned(response_id, task_id), CandidateResponse.transcription_status == TranscriptionStatus.COMPLETED)
            .values(
                evaluation_status=EvaluationStatus.PROCESSING,
                evaluation_attempts=CandidateResponse.evaluation_attempts + 1,
                evaluation_error=None,
            )
        )
        db.commit()
        return result.rowcount == 1


def _finish(factory: sessionmaker, response_id: uuid.UUID, task_id: str, status: EvaluationStatus, code: str | None) -> bool:
    with factory() as db:
        result = db.execute(
            sa.update(CandidateResponse)
            .where(*_owned(response_id, task_id))
            .values(evaluation_status=status, evaluation_error=(code[:100] if code else None))
        )
        db.commit()
        return result.rowcount == 1


def mark_failed(factory: sessionmaker, response_id: uuid.UUID, task_id: str, code: str) -> bool:
    return _finish(factory, response_id, task_id, EvaluationStatus.FAILED, code)


def _session_id(factory: sessionmaker, response_id: uuid.UUID) -> uuid.UUID | None:
    with factory() as db:
        return db.scalar(sa.select(CandidateResponse.session_id).where(CandidateResponse.id == response_id))


def _persist(factory: sessionmaker, response_id: uuid.UUID, task_id: str, result: ValidatedEvaluation) -> Outcome:
    """ONE transaction: flip the answer to COMPLETED (guarded by ownership) and insert the evaluation.
    Both happen or neither does. The unique response_id constraint is the last line of defence against doubles."""
    with factory() as db:
        try:
            updated = db.execute(
                sa.update(CandidateResponse)
                .where(*_owned(response_id, task_id, (EvaluationStatus.PROCESSING,)))
                .values(evaluation_status=EvaluationStatus.COMPLETED, evaluation_error=None)
            )
            if updated.rowcount != 1:
                db.rollback()
                return Outcome("skipped", "ownership_lost")
            fields = {**result.fields, "recommendation": Recommendation(result.fields["recommendation"])}
            db.add(Evaluation(response_id=response_id, **fields))
            db.commit()
        except IntegrityError:
            db.rollback()
            # Only a duplicate if the evaluation row REALLY exists. Any other integrity error (CHECK, FK, ...) must
            # never be reported as "already evaluated": nothing was stored, so the answer is marked failed.
            exists = db.scalar(sa.select(sa.exists().where(Evaluation.response_id == response_id)))
            if exists:
                logger.info("Evaluation already exists response_id=%s", response_id)
                _finish(factory, response_id, task_id, EvaluationStatus.COMPLETED, None)
                return Outcome("skipped", "already_evaluated")
            logger.error("Evaluation rejected by the database response_id=%s", response_id)
            raise EvaluationFailure("persistence_rejected", "The database rejected the evaluation.", retryable=False) from None
        except SQLAlchemyError as exc:
            db.rollback()
            logger.error("Evaluation persistence failed response_id=%s error=%s", response_id, type(exc).__name__)
            raise EvaluationFailure("persistence_error", "The evaluation could not be saved.", retryable=True) from None
    return Outcome("evaluated")


def run(
    factory: sessionmaker,
    response_id: uuid.UUID,
    task_id: str,
    settings: Settings,
    provider: EvaluationProvider | None = None,
) -> Outcome:
    """Evaluate one answer. Raises EvaluationFailure ONLY for retryable failures (the Celery task retries);
    permanent failures are recorded on the answer and returned as Outcome('failed', code)."""
    if not claim(factory, response_id, task_id):
        logger.info("Skipping evaluation response_id=%s: not owned by task %s or already finished", response_id, task_id)
        return Outcome("skipped", "not_owner")

    outcome = _evaluate_claimed(factory, response_id, task_id, settings, provider)
    session_id = _session_id(factory, response_id)
    if session_id is not None:
        coordination.refresh_session_status(factory, session_id)
    return outcome


def _evaluate_claimed(factory, response_id, task_id, settings, provider) -> Outcome:
    with factory() as db:
        row = db.execute(
            sa.select(
                CandidateResponse.transcript, CandidateResponse.no_speech_detected,
                Question.text, Question.question_type, Question.rubric_key, Interview.rubric_name,
                sa.exists().where(Evaluation.response_id == response_id),
            )
            .join(Question, Question.id == CandidateResponse.question_id)
            .join(Interview, Interview.id == Question.interview_id)
            .where(CandidateResponse.id == response_id)
        ).one_or_none()
    if row is None:
        mark_failed(factory, response_id, task_id, "question_missing")
        return Outcome("failed", "question_missing")
    transcript, no_speech, question_text, question_type, rubric_key, rubric_name, already = row

    if already:  # duplicate protection even if the status flag was lost
        _finish(factory, response_id, task_id, EvaluationStatus.COMPLETED, None)
        return Outcome("skipped", "already_evaluated")
    if no_speech:  # a system outcome, not a zero score: no model call, no Evaluation row
        _finish(factory, response_id, task_id, EvaluationStatus.SKIPPED, "no_speech")
        return Outcome("skipped", "no_speech")
    if not transcript or not transcript.strip():
        mark_failed(factory, response_id, task_id, "transcript_missing")
        return Outcome("failed", "transcript_missing")

    try:
        provider = provider or get_evaluation_provider(settings)
        result = evaluate_transcript(
            provider=provider, rubrics_dir=settings.rubrics_path, rubric_name=rubric_name,
            question_text=question_text, question_type=question_type, rubric_key=rubric_key, transcript=transcript,
        )
        # Day 5: add the NLP enrichment to the already validated and scored result. It cannot fail the evaluation
        # (enrich_fields never raises) and cannot change a score: only the `nlp_enrichment` field is replaced.
        result = replace(result, fields=enrich_fields(result.fields, transcript, question_text, settings))
        return _persist(factory, response_id, task_id, result)
    except EvaluationProviderError as exc:  # raised by the factory (missing key, unsupported provider)
        failure = EvaluationFailure(exc.code, str(exc), retryable=exc.retryable, retry_after=exc.retry_after)
    except EvaluationFailure as exc:
        failure = exc
    if failure.retryable:
        raise failure  # the Celery task decides whether retries are left
    mark_failed(factory, response_id, task_id, failure.code)
    logger.warning("Evaluation failed response_id=%s code=%s", response_id, failure.code)
    return Outcome("failed", failure.code)
