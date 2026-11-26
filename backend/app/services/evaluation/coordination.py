"""Transcription <-> evaluation <-> session-status coordination (Day 4, Phase 3).

`classify_response` and `decide_session_status` are pure and fully unit-tested. `refresh_session_status`
reads the session's answers from the database and applies the decision with a guarded UPDATE.

Per-answer states
  TRANSCRIPTION_OPEN     pending/processing transcription          -> unfinished
  TRANSCRIPTION_FAILED   transcription failed                      -> failure (retry via the existing retry endpoint)
  NO_SPEECH              completed, nothing was said               -> system outcome, NOT a zero score, not a failure
  MISSING_TRANSCRIPT     completed but the text is missing/blank   -> failure (data problem)
  EVALUATION_OPEN        transcript ready, evaluation pending/processing -> unfinished
  EVALUATED / EVALUATION_FAILED / EVALUATION_SKIPPED

Session rule (existing conventions: submitted -> processing -> evaluated | failed)
  any unfinished answer                              -> PROCESSING   (never EVALUATED)
  all finished, no failure, at least one EVALUATED   -> EVALUATED
  all finished, otherwise                            -> FAILED       (needs attention; reasons are per answer)
  no answers at all                                  -> no change
Only sessions in SUBMITTED / PROCESSING / FAILED are touched; an EVALUATED session is final, and a session
the candidate has not submitted yet is never advanced.
"""

from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models import CandidateResponse, InterviewSession, SessionStatus
from app.services.evaluation.states import ResponseState, classify_response, decide_session_status  # noqa: F401

logger = logging.getLogger(__name__)

REFRESHABLE = (SessionStatus.SUBMITTED, SessionStatus.PROCESSING, SessionStatus.FAILED)


def refresh_session_status(factory: sessionmaker, session_id: uuid.UUID) -> SessionStatus | None:
    """Recompute the session status from its answers. Never raises (a status refresh must not fail a task)."""
    try:
        with factory() as db:
            current = db.scalar(sa.select(InterviewSession.status).where(InterviewSession.id == session_id))
            if current not in REFRESHABLE:
                return None
            length = sa.func.coalesce(sa.func.length(sa.func.trim(CandidateResponse.transcript)), 0)
            rows = db.execute(
                sa.select(
                    CandidateResponse.transcription_status, CandidateResponse.no_speech_detected,
                    length, CandidateResponse.evaluation_status,
                ).where(CandidateResponse.session_id == session_id)
            ).all()
            value = decide_session_status([classify_response(*row) for row in rows])
            decided = SessionStatus(value) if value else None
            if decided is None or decided == current:
                return decided
            changed = db.execute(
                sa.update(InterviewSession)
                .where(InterviewSession.id == session_id, InterviewSession.status.in_(REFRESHABLE))
                .values(status=decided)
            )
            db.commit()
            logger.info("Session %s status %s -> %s (updated=%s)", session_id, current.value, decided.value, changed.rowcount == 1)
            return decided
    except Exception as exc:  # noqa: BLE001
        logger.error("Session status refresh failed session_id=%s error=%s", session_id, type(exc).__name__)
        return None
