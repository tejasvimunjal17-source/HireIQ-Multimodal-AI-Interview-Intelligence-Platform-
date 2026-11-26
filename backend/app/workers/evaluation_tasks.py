"""Celery task that evaluates one transcribed answer (Day 4, Phase 3)."""

import logging
import uuid

from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.evaluation import coordination, engine
from app.services.evaluation.engine import EvaluationFailure
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_settings = get_settings()


@celery_app.task(
    bind=True,
    name="hireiq.evaluate_response",
    max_retries=_settings.evaluation_max_retries,
    soft_time_limit=420,
    time_limit=480,
)
def evaluate_response(self, response_id: str) -> dict[str, str]:
    """Evaluate ONE CandidateResponse. Only the id travels through Redis; the result holds a status and a code,
    never transcript or model text. Safe to deliver twice: only the task whose id was stored at dispatch can
    claim the answer, and the evaluation row is unique per answer (see engine.claim / engine._persist)."""
    settings = get_settings()
    rid = uuid.UUID(response_id)
    task_id = str(self.request.id)
    factory = get_session_factory()

    try:
        return engine.run(factory, rid, task_id, settings).as_dict()
    except SoftTimeLimitExceeded:
        failure = EvaluationFailure("task_timeout", "The task ran too long.", retryable=True)
    except EvaluationFailure as exc:
        failure = exc
    except Exception as exc:  # noqa: BLE001 - a bug must not loop forever or lose the answer
        logger.error("Unexpected error in evaluation task response_id=%s error=%s", rid, type(exc).__name__)
        _fail(factory, rid, task_id, "internal_error")
        return {"status": "failed", "code": "internal_error"}

    limit = self.max_retries if failure.max_retries is None else min(self.max_retries, failure.max_retries)
    if failure.retryable and self.request.retries < limit:
        delay = engine.backoff_seconds(self.request.retries, settings.evaluation_retry_backoff_seconds, failure.retry_after)
        logger.warning(
            "Retrying evaluation response_id=%s in %ss (retry %d of %d, code=%s)",
            rid, delay, self.request.retries + 1, limit, failure.code,
        )
        raise self.retry(exc=failure, countdown=delay)

    _fail(factory, rid, task_id, failure.code)  # retries used up: record it; nothing unvalidated is stored
    return {"status": "failed", "code": failure.code}


def _fail(factory, rid: uuid.UUID, task_id: str, code: str) -> None:
    try:
        engine.mark_failed(factory, rid, task_id, code)
        session_id = engine._session_id(factory, rid)
        if session_id is not None:
            coordination.refresh_session_status(factory, session_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not record evaluation failure response_id=%s error=%s", rid, type(exc).__name__)
