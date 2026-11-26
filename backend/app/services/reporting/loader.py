"""Reads ONE session's stored data for the PDF (Day 6). Read-only: no writes, no model calls, no commit.

Scoping: every query is restricted to the requested session (`session_id`) and to that session's own interview, so
data of another candidate or session can never appear. Candidate e-mail is deliberately not loaded (data minimisation).
"""

from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import CandidateResponse, Evaluation, InterviewSession, Question, Report
from app.services.reporting.data import ReportData, build_report

logger = logging.getLogger(__name__)


def load_report_data(db: Session, session_id: uuid.UUID) -> ReportData:
    """Raises HTTPException 404 (no such session) or 409 (nothing evaluated yet, so a report would mislead)."""
    data = load_session_data(db, session_id)
    if not data.evaluated:
        raise HTTPException(status_code=409, detail="No answer of this session has been evaluated yet, so there is no report to generate.")
    return data


def load_session_data(db: Session, session_id: uuid.UUID) -> ReportData:
    """Everything stored for ONE session, sanitised (also used by the Day 7 dashboard detail view).
    Raises HTTPException 404 for an unknown session; a session without evaluations is returned as is."""
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found.")

    rows = db.execute(
        sa.select(Question, CandidateResponse, Evaluation)
        .outerjoin(
            CandidateResponse,
            sa.and_(CandidateResponse.question_id == Question.id, CandidateResponse.session_id == session.id),
        )
        .outerjoin(Evaluation, Evaluation.response_id == CandidateResponse.id)
        .where(Question.interview_id == session.interview_id)
        .order_by(Question.position)
    ).all()
    stored = db.scalar(sa.select(Report).where(Report.session_id == session.id))

    answers = []
    for question, response, evaluation in rows:
        raw = {"position": question.position, "question": question.text, "answered": response is not None}
        if response is not None:
            raw.update(
                transcript=response.transcript, transcription_status=response.transcription_status,
                no_speech=response.no_speech_detected, evaluation_status=response.evaluation_status,
                evaluation_error=response.evaluation_error,
            )
        if evaluation is not None:
            raw["evaluation"] = {
                "overall_score": evaluation.overall_score, "recommendation": evaluation.recommendation,
                "explanation": evaluation.explanation, "criteria_scores": evaluation.criteria_scores,
                "evaluation_details": evaluation.evaluation_details, "nlp_enrichment": evaluation.nlp_enrichment,
            }
        answers.append(raw)

    data = build_report(
        session_id=session.id, session_status=session.status, candidate_id=session.candidate_id,
        candidate_name=session.candidate.full_name, interview_title=session.interview.title,
        interview_date=session.completed_at or session.started_at or session.created_at, answers=answers,
        stored_overall_score=stored.overall_score if stored else None,
        stored_recommendation=stored.recommendation if stored else None,
    )
    logger.info("Session data loaded session_id=%s answers=%d evaluated=%d", session.id, len(data.answers), len(data.evaluated))
    return data
