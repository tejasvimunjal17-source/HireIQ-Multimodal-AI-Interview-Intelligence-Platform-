"""Create the database rows needed by transcription tests."""

import uuid

from sqlalchemy.orm import Session

from app.models import (
    Candidate, CandidateResponse, Interview, InterviewSession, Question, QuestionType, TranscriptionStatus,
)


def make_response(db: Session, *, task_id: str | None = "task-1", status: TranscriptionStatus = TranscriptionStatus.PENDING, **fields):
    """Returns (response, session). One candidate, one interview with 2 questions, one answer."""
    candidate = Candidate(full_name="Test Candidate", email=f"{uuid.uuid4().hex[:10]}@example.com")
    interview = Interview(title="T", rubric_name="default", questions=[
        Question(position=1, text="Q1", question_type=QuestionType.TECHNICAL),
        Question(position=2, text="Q2", question_type=QuestionType.BEHAVIORAL),
    ])
    session = InterviewSession(candidate=candidate, interview=interview)
    response = CandidateResponse(
        session=session, question=interview.questions[0], transcription_status=status, celery_task_id=task_id, **fields
    )
    db.add_all([candidate, interview, session, response])
    db.commit()
    return response, session


def reload(db: Session, response_id) -> CandidateResponse:
    db.expire_all()
    return db.get(CandidateResponse, response_id)
