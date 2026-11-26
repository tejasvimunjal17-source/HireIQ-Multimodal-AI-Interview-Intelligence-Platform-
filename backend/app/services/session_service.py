"""Candidate interview session logic (Day 2): start, view, receive answers, complete."""

import logging
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Candidate, CandidateResponse, Interview, InterviewSession, Question, SessionStatus, TranscriptionStatus,
)
from app.schemas.interview import (
    InterviewSummary, QuestionPublic, ResponseReceipt, SessionCompleteResponse, SessionStartRequest, SessionView,
)
from app.services import audio_intake
from app.services.transcription_dispatch import dispatch_transcription

logger = logging.getLogger(__name__)

# Once a session reaches one of these, candidates can no longer upload answers.
LOCKED_STATUSES = {
    SessionStatus.SUBMITTED, SessionStatus.PROCESSING, SessionStatus.EVALUATED, SessionStatus.FAILED,
}


def _summary(interview: Interview, question_count: int) -> InterviewSummary:
    return InterviewSummary(
        id=interview.id,
        title=interview.title,
        description=interview.description,
        interview_type=interview.interview_type.value,
        question_count=question_count,
        total_time_limit_seconds=interview.total_time_limit_seconds,
    )


def list_active_interviews(db: Session, limit: int) -> list[InterviewSummary]:
    count = sa.func.count(Question.id)
    stmt = (
        sa.select(Interview, count)
        .join(Question, Question.interview_id == Interview.id)  # inner join: skips interviews with no questions
        .where(Interview.is_active.is_(True))
        .group_by(Interview.id)
        .order_by(Interview.created_at.desc(), Interview.id)
        .limit(limit)
    )
    return [_summary(interview, total) for interview, total in db.execute(stmt).all()]


def _get_session_or_404(db: Session, session_id: uuid.UUID) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found.")
    return session


def build_session_view(db: Session, session: InterviewSession) -> SessionView:
    questions = list(session.interview.questions)  # ordered by position
    answered = db.scalars(
        sa.select(CandidateResponse.question_id).where(CandidateResponse.session_id == session.id)
    ).all()
    return SessionView(
        session_id=session.id,
        status=session.status.value,
        interview=_summary(session.interview, len(questions)),
        questions=[
            QuestionPublic(
                id=q.id, position=q.position, text=q.text,
                question_type=q.question_type.value, time_limit_seconds=q.time_limit_seconds,
            )
            for q in questions
        ],
        answered_question_ids=list(answered),
    )


def get_session_view(db: Session, session_id: uuid.UUID) -> SessionView:
    return build_session_view(db, _get_session_or_404(db, session_id))


def start_session(db: Session, request: SessionStartRequest) -> SessionView:
    interview = db.get(Interview, request.interview_id)
    if interview is None or not interview.is_active or not interview.questions:
        raise HTTPException(status_code=404, detail="Interview not found or not available.")

    candidate = db.scalar(sa.select(Candidate).where(Candidate.email == request.candidate_email))
    now = datetime.now(timezone.utc)
    if candidate is None:
        candidate = Candidate(full_name=request.candidate_name, email=request.candidate_email, consent_given_at=now)
        db.add(candidate)
        db.flush()
    else:
        if candidate.consent_given_at is None:
            candidate.consent_given_at = now
        existing = db.scalar(
            sa.select(InterviewSession.id).where(
                InterviewSession.candidate_id == candidate.id, InterviewSession.interview_id == interview.id
            )
        )
        if existing is not None:
            # Do not hand back someone else's session just because the email matches.
            raise HTTPException(status_code=409, detail="A session already exists for this email and interview.")

    session = InterviewSession(candidate_id=candidate.id, interview_id=interview.id)
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A session already exists for this email and interview.")
    db.refresh(session)
    return build_session_view(db, session)


def receive_response(
    db: Session,
    settings: Settings,
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    duration_seconds: float | None,
    upload: UploadFile,
) -> ResponseReceipt:
    session = _get_session_or_404(db, session_id)
    if session.status in LOCKED_STATUSES:
        raise HTTPException(status_code=409, detail="This interview has already been submitted.")

    question = db.get(Question, question_id)
    if question is None or question.interview_id != session.interview_id:
        raise HTTPException(status_code=404, detail="Question not found in this interview.")

    already = db.scalar(
        sa.select(CandidateResponse.id).where(
            CandidateResponse.session_id == session.id, CandidateResponse.question_id == question.id
        )
    )
    if already is not None:
        raise HTTPException(status_code=409, detail="This question has already been answered.")

    response_id = uuid.uuid4()
    try:
        saved = audio_intake.save_upload(upload, response_id, settings.audio_temp_dir, settings.audio_max_upload_bytes)
    except audio_intake.AudioValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    try:
        db.add(
            CandidateResponse(
                id=response_id,
                session_id=session.id,
                question_id=question.id,
                transcription_status=TranscriptionStatus.PENDING,
                audio_duration_seconds=duration_seconds,
            )
        )
        if session.status == SessionStatus.CREATED:
            session.status = SessionStatus.IN_PROGRESS
            session.started_at = datetime.now(timezone.utc)
        db.commit()
    except IntegrityError:
        db.rollback()
        audio_intake.delete_audio(response_id, settings.audio_temp_dir)
        raise HTTPException(status_code=409, detail="This question has already been answered.")
    except Exception:
        db.rollback()
        audio_intake.delete_audio(response_id, settings.audio_temp_dir)
        raise

    task_id = dispatch_transcription(response_id)  # queues Celery work; never raises
    logger.info("Stored answer response_id=%s size_bytes=%d", response_id, saved.size_bytes)
    return ResponseReceipt(
        response_id=response_id,
        question_id=question.id,
        transcription_status="pending",
        size_bytes=saved.size_bytes,
        content_type=saved.content_type,
        task_id=task_id,
    )


def complete_session(db: Session, session_id: uuid.UUID) -> SessionCompleteResponse:
    session = _get_session_or_404(db, session_id)
    if session.status in LOCKED_STATUSES:
        return SessionCompleteResponse(session_id=session.id, status=session.status.value)  # idempotent

    total = db.scalar(sa.select(sa.func.count(Question.id)).where(Question.interview_id == session.interview_id))
    answered = db.scalar(
        sa.select(sa.func.count(CandidateResponse.id)).where(CandidateResponse.session_id == session.id)
    )
    remaining = (total or 0) - (answered or 0)
    if remaining > 0:
        raise HTTPException(status_code=409, detail=f"{remaining} question(s) are still unanswered.")

    session.status = SessionStatus.SUBMITTED
    session.completed_at = datetime.now(timezone.utc)
    db.commit()
    # Day 4: answers may have been evaluated before the candidate pressed "submit". Settle the status only when
    # EVERY answer is already finished; otherwise it stays 'submitted' until the evaluation tasks update it.
    settled = _settle_if_all_finished(db, session.id)
    return SessionCompleteResponse(session_id=session.id, status=(settled or session.status).value)


def _settle_if_all_finished(db: Session, session_id: uuid.UUID) -> SessionStatus | None:
    from app.services.evaluation import coordination  # lazy import: keeps API start-up light

    length = sa.func.coalesce(sa.func.length(sa.func.trim(CandidateResponse.transcript)), 0)
    rows = db.execute(
        sa.select(
            CandidateResponse.transcription_status, CandidateResponse.no_speech_detected, length,
            CandidateResponse.evaluation_status,
        ).where(CandidateResponse.session_id == session_id)
    ).all()
    states = [coordination.classify_response(*row) for row in rows]
    if not states or any(s in (coordination.ResponseState.TRANSCRIPTION_OPEN, coordination.ResponseState.EVALUATION_OPEN) for s in states):
        return None  # still unfinished: stay 'submitted'
    bind = db.get_bind()
    from sqlalchemy.orm import sessionmaker
    return coordination.refresh_session_status(sessionmaker(bind=bind, autoflush=False, expire_on_commit=False), session_id)
