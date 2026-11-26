import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.schemas.health import ErrorResponse
from app.schemas.interview import (
    ResponseReceipt, SessionCompleteResponse, SessionStartRequest, SessionView, TranscriptionView,
)
from app.services import session_service, transcription_status

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
ERRORS = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.post("", response_model=SessionView, status_code=201, responses=ERRORS)
def start_session(body: SessionStartRequest, db: Session = Depends(get_db)):
    """Create the candidate (name + email + consent) and an interview session."""
    return session_service.start_session(db, body)


@router.get("/{session_id}", response_model=SessionView, responses=ERRORS)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """Used to resume an interview after a page refresh."""
    return session_service.get_session_view(db, session_id)


@router.post(
    "/{session_id}/responses",
    response_model=ResponseReceipt,
    status_code=201,
    responses={**ERRORS, 413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
def submit_response(
    session_id: uuid.UUID,
    question_id: uuid.UUID = Form(...),
    duration_seconds: float | None = Form(None, ge=0, le=3600),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Receive ONE recorded answer (multipart/form-data). The audio is stored temporarily and queued for asynchronous transcription; the response returns a `task_id`."""
    return session_service.receive_response(db, settings, session_id, question_id, duration_seconds, audio)


@router.post("/{session_id}/complete", response_model=SessionCompleteResponse, responses=ERRORS)
def complete_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """Mark the interview as submitted once every question has an answer."""
    return session_service.complete_session(db, session_id)


@router.get("/{session_id}/transcriptions", response_model=list[TranscriptionView], responses=ERRORS)
def list_transcriptions(session_id: uuid.UUID, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Transcription status of every answer in the session (cheap to poll)."""
    return transcription_status.list_transcriptions(db, settings, session_id)


@router.get("/{session_id}/responses/{response_id}/transcription", response_model=TranscriptionView, responses=ERRORS)
def get_transcription(
    session_id: uuid.UUID, response_id: uuid.UUID,
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
):
    return transcription_status.get_transcription(db, settings, session_id, response_id)


@router.post(
    "/{session_id}/responses/{response_id}/transcription/retry",
    response_model=TranscriptionView, status_code=202, responses=ERRORS,
)
def retry_transcription(
    session_id: uuid.UUID, response_id: uuid.UUID,
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
):
    """Re-queue a failed (or never-queued / stuck) answer while its audio is still retained."""
    return transcription_status.retry_transcription(db, settings, session_id, response_id)
