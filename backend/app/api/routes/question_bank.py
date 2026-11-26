"""Manager-only question bank and rubric catalogue (Day 8).

All routes need the same bearer token as the PDF and dashboard routes (REPORT_ACCESS_TOKEN); the token is checked
before anything is read or written. The public candidate API (/api/interviews, /api/sessions) is unchanged and
still shows candidates neither rubric details nor the new question metadata.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.reports import require_report_access
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.schemas.health import ErrorResponse
from app.schemas.question_bank import (
    ActivationRequest, DifficultyName, InterviewCreate, InterviewDetail, QuestionBankItem, QuestionBankPage, QuestionCreate,
    QuestionTypeName, RubricInfo,
)
from app.services import question_bank as service

router = APIRouter(
    prefix="/api/question-bank", tags=["question-bank"], dependencies=[Depends(require_report_access)],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)


@router.get("/rubrics", response_model=list[RubricInfo])
def list_rubrics(settings: Settings = Depends(get_settings)):
    """Rubric files with their keys, criteria names and weights (no prompt examples). Invalid files are listed as invalid."""
    return service.list_rubrics(settings.rubrics_path)


@router.post("/interviews", response_model=InterviewDetail, status_code=201,
             responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def create_interview(payload: InterviewCreate, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """New interview template. It starts inactive (hidden from candidates) until it has questions and is activated."""
    return service.create_interview(db, payload, settings.rubrics_path)


@router.put("/interviews/{interview_id}/active", response_model=InterviewDetail,
            responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def set_interview_active(interview_id: uuid.UUID, payload: ActivationRequest, db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings)):
    """Show (true) or hide (false) the interview for candidates. Activation needs at least one question and a valid rubric."""
    return service.set_interview_active(db, interview_id, payload.active, settings.rubrics_path)


@router.post("/interviews/{interview_id}/questions", response_model=QuestionBankItem, status_code=201,
             responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def create_question(interview_id: uuid.UUID, payload: QuestionCreate, db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)):
    """Add a question to an interview that has no sessions yet."""
    return service.create_question(db, interview_id, payload, settings.rubrics_path)


@router.get("/questions", response_model=QuestionBankPage, responses={422: {"model": ErrorResponse}})
def list_questions(
    interview_id: uuid.UUID | None = None,
    question_type: QuestionTypeName | None = None,
    category: str | None = Query(None, max_length=50),
    difficulty: DifficultyName | None = None,
    skill: str | None = Query(None, max_length=60, description="One whole entry of expected_skills"),
    search: str | None = Query(None, max_length=100, description="Question text contains"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """Questions of all interviews, filterable; ordered by interview title then position."""
    return service.list_questions(db, interview_id=interview_id, question_type=question_type, category=category, difficulty=difficulty,
                                  skill=skill, search=search, page=page, page_size=page_size)


@router.get("/questions/{question_id}", response_model=QuestionBankItem, responses={404: {"model": ErrorResponse}})
def get_question(question_id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_question(db, question_id)
