"""Question-bank use cases (Day 8). Manager-only; the candidate API and the evaluation pipeline are not touched.

Rules enforced here (the schemas enforce the field shapes):
- A question's rubric_key (or, when empty, its type) must exist in the interview's rubric file, so a question that
  is stored can always be evaluated by the Day 4 pipeline.
- A technical interview takes technical questions only, a behavioral one behavioral only; "mixed" takes both.
- Questions can only be added while the interview has NO sessions: candidates may already be answering it, and
  adding a question would change what "all answered" means and silently mix results of different question sets.
- No duplicate question text within one interview (case-insensitive); at most 50 questions; positions are unique.
- A new interview starts INACTIVE (candidates cannot see it) and can only be activated when it has questions.
Writes are limited to `interviews` and `questions`. Candidate data is never read.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Difficulty, Interview, InterviewSession, InterviewType, Question, QuestionType
from app.schemas.question_bank import (
    MAX_QUESTIONS_PER_INTERVIEW, InterviewCreate, InterviewDetail, QuestionBankItem, QuestionBankPage, QuestionCreate,
    RubricInfo, normalise_category, normalise_skill_filter,
)
from app.services.rubrics.catalog import describe_rubric, resolve_rubric_key, validate_rubrics_dir
from app.services.rubrics.loader import RubricError, RubricNotFoundError, load_rubric

logger = logging.getLogger(__name__)
MAX_PAGE_SIZE = 100


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _interview_detail(db: Session, interview: Interview) -> InterviewDetail:
    count = db.scalar(sa.select(sa.func.count(Question.id)).where(Question.interview_id == interview.id)) or 0
    return InterviewDetail(
        id=interview.id, title=interview.title, description=interview.description,
        interview_type=getattr(interview.interview_type, "value", interview.interview_type), rubric_name=interview.rubric_name,
        total_time_limit_seconds=interview.total_time_limit_seconds, is_active=interview.is_active, question_count=count,
    )


def _item(question: Question, title: str) -> QuestionBankItem:
    return QuestionBankItem(
        id=question.id, interview_id=question.interview_id, interview_title=title, position=question.position, text=question.text,
        question_type=getattr(question.question_type, "value", question.question_type), rubric_key=question.rubric_key,
        category=question.category, difficulty=getattr(question.difficulty, "value", question.difficulty),
        expected_skills=list(question.expected_skills or []), time_limit_seconds=question.time_limit_seconds,
    )


def _load_interview_rubric(interview_rubric_name: str, rubrics_dir: Path):
    try:
        return load_rubric(interview_rubric_name, rubrics_dir)
    except RubricNotFoundError:
        raise HTTPException(status_code=422, detail=f"Rubric '{interview_rubric_name}' does not exist in the rubric folder.") from None
    except RubricError:
        # The operator's file is broken; do not echo its content to the API caller.
        raise HTTPException(status_code=409, detail=f"Rubric '{interview_rubric_name}' is invalid. Run: python -m app.scripts.validate_rubrics") from None


# ---------------------------------------------------------------- rubrics
def list_rubrics(rubrics_dir: Path) -> list[RubricInfo]:
    result: list[RubricInfo] = []
    for report in validate_rubrics_dir(rubrics_dir):
        if report.valid and report.rubric is not None:
            result.append(RubricInfo(valid=True, **describe_rubric(report.rubric)))
        else:
            first_line = report.error.splitlines()[0] if report.error else "Invalid rubric."
            result.append(RubricInfo(name=report.name, valid=False, problem=first_line))
    return result


# ---------------------------------------------------------------- interviews
def create_interview(db: Session, payload: InterviewCreate, rubrics_dir: Path) -> InterviewDetail:
    _load_interview_rubric(payload.rubric_name, rubrics_dir)  # must exist and be valid
    interview = Interview(
        title=payload.title, description=payload.description, interview_type=InterviewType(payload.interview_type),
        rubric_name=payload.rubric_name, total_time_limit_seconds=payload.total_time_limit_seconds, is_active=False,
    )
    db.add(interview)
    db.commit()
    logger.info("Interview created id=%s", interview.id)
    return _interview_detail(db, interview)


def set_interview_active(db: Session, interview_id: uuid.UUID, active: bool, rubrics_dir: Path) -> InterviewDetail:
    interview = db.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found.")
    if active:
        questions = db.scalars(sa.select(Question).where(Question.interview_id == interview_id)).all()
        if not questions:
            raise HTTPException(status_code=409, detail="An interview needs at least one question before it can be activated.")
        rubric = _load_interview_rubric(interview.rubric_name, rubrics_dir)
        for question in questions:
            try:
                resolve_rubric_key(rubric, question.rubric_key, question.question_type)
            except KeyError as exc:
                raise HTTPException(status_code=409, detail=f"Question {question.position} cannot be evaluated: {exc.args[0]}") from None
    interview.is_active = active
    db.commit()
    return _interview_detail(db, interview)


# ---------------------------------------------------------------- questions
def create_question(db: Session, interview_id: uuid.UUID, payload: QuestionCreate, rubrics_dir: Path) -> QuestionBankItem:
    interview = db.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found.")
    if db.scalar(sa.select(sa.func.count(InterviewSession.id)).where(InterviewSession.interview_id == interview_id)):
        raise HTTPException(status_code=409, detail="This interview already has sessions; questions can no longer be added to it. Create a new interview instead.")

    itype = getattr(interview.interview_type, "value", interview.interview_type)
    if itype != "mixed" and payload.question_type != itype:
        raise HTTPException(status_code=422, detail=f"A {itype} interview accepts {itype} questions only.")

    rubric = _load_interview_rubric(interview.rubric_name, rubrics_dir)
    try:
        resolve_rubric_key(rubric, payload.rubric_key, payload.question_type)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=exc.args[0]) from None

    existing = db.execute(sa.select(Question.position, Question.text).where(Question.interview_id == interview_id)).all()
    if len(existing) >= MAX_QUESTIONS_PER_INTERVIEW:
        raise HTTPException(status_code=409, detail=f"An interview can have at most {MAX_QUESTIONS_PER_INTERVIEW} questions.")
    if any(text.strip().casefold() == payload.text.casefold() for _, text in existing):
        raise HTTPException(status_code=409, detail="This interview already contains a question with the same text.")
    position = payload.position if payload.position is not None else max((p for p, _ in existing), default=0) + 1
    if any(p == position for p, _ in existing):
        raise HTTPException(status_code=409, detail=f"Position {position} is already used in this interview.")

    question = Question(
        interview_id=interview_id, position=position, text=payload.text, question_type=QuestionType(payload.question_type),
        rubric_key=payload.rubric_key or payload.question_type, category=payload.category,
        difficulty=Difficulty(payload.difficulty) if payload.difficulty else None,
        expected_skills=payload.expected_skills or None, time_limit_seconds=payload.time_limit_seconds,
    )
    db.add(question)
    try:
        db.commit()
    except sa.exc.IntegrityError:  # two requests raced for the same position
        db.rollback()
        raise HTTPException(status_code=409, detail="Another question was added at the same time; please retry.") from None
    logger.info("Question created id=%s interview_id=%s", question.id, interview_id)  # never the question text
    return _item(question, interview.title)


def get_question(db: Session, question_id: uuid.UUID) -> QuestionBankItem:
    row = db.execute(
        sa.select(Question, Interview.title).join(Interview, Interview.id == Question.interview_id).where(Question.id == question_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    return _item(row[0], row[1])


def list_questions(
    db: Session, *, interview_id: uuid.UUID | None = None, question_type: str | None = None, category: str | None = None,
    difficulty: str | None = None, skill: str | None = None, search: str | None = None, page: int = 1, page_size: int = 20,
) -> QuestionBankPage:
    """Filters combine with AND. category/skill are normalised exactly like stored values; skill matches one whole
    entry of expected_skills (not a substring of another skill)."""
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise HTTPException(status_code=422, detail=f"page must be >= 1 and page_size between 1 and {MAX_PAGE_SIZE}.")
    query = sa.select(Question, Interview.title).join(Interview, Interview.id == Question.interview_id)
    if interview_id is not None:
        query = query.where(Question.interview_id == interview_id)
    if question_type is not None:
        query = query.where(Question.question_type == QuestionType(question_type))
    if difficulty is not None:
        query = query.where(Question.difficulty == Difficulty(difficulty))
    try:
        if category:
            query = query.where(Question.category == normalise_category(category))
        if skill:
            wanted = normalise_skill_filter(skill)
            # expected_skills is a JSON list of normalised strings; the quotes make this a whole-entry match.
            query = query.where(sa.cast(Question.expected_skills, sa.String).like(f'%"{_like_escape(wanted)}"%', escape="\\"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    term = (search or "").strip()
    if term:
        query = query.where(Question.text.ilike(f"%{_like_escape(term[:100])}%", escape="\\"))

    total = db.scalar(sa.select(sa.func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(Interview.title, Question.position, Question.id).limit(page_size).offset((page - 1) * page_size)
    ).all()
    return QuestionBankPage(items=[_item(q, title) for q, title in rows], total=total, page=page, page_size=page_size)
