from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.interview import InterviewSummary
from app.services import session_service

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


@router.get("", response_model=list[InterviewSummary])
def list_interviews(limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    """Active interviews a candidate can start (bounded list)."""
    return session_service.list_active_interviews(db, limit)
