"""Hiring-manager dashboard API (Day 7). READ-ONLY.

All routes need the same bearer token as the PDF download (REPORT_ACCESS_TOKEN): the API has no user accounts yet, and
these views contain candidate names and evaluations. The token is typed in by the manager at run time and is never part
of the frontend code. With no token configured the dashboard API is disabled (503).
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.reports import require_report_access
from app.core.database import get_db
from app.models import Recommendation, SessionStatus
from app.schemas.dashboard import DashboardSummary, SessionDetail, SessionPage
from app.schemas.health import ErrorResponse
from app.services import dashboard as service

router = APIRouter(
    prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_report_access)],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)


@router.get("/summary", response_model=DashboardSummary)
def get_summary(db: Session = Depends(get_db)):
    """Totals and the score distribution over ALL sessions (computed from stored rows)."""
    return service.summary(db)


@router.get("/sessions", response_model=SessionPage, responses={422: {"model": ErrorResponse}})
def list_sessions(
    search: str | None = Query(None, max_length=100, description="Candidate name contains (case-insensitive)"),
    interview_id: uuid.UUID | None = None,
    status: SessionStatus | None = None,
    recommendation: Recommendation | None = Query(None, description="Has at least one evaluated answer with this stored advice"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=service.MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """Sessions, newest first. No transcripts, no e-mail addresses."""
    return service.list_sessions(db, search=search, interview_id=interview_id, status=status, recommendation=recommendation, page=page, page_size=page_size)


@router.get("/sessions/{session_id}", response_model=SessionDetail, responses={404: {"model": ErrorResponse}})
def get_session_detail(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """Stored evaluation of ONE session (no transcript; download the PDF for the full record)."""
    return service.session_detail(db, session_id)
