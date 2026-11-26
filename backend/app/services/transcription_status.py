"""Read-side of transcription: status views and the manual retry/recovery action."""

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CandidateResponse, InterviewSession, TranscriptionStatus
from app.schemas.interview import TranscriptionView
from app.services import audio_intake
from app.services.transcription_dispatch import dispatch_transcription

ERROR_MESSAGES = {
    "audio_empty": "The recording was empty.",
    "audio_too_short": "The recording was too short to transcribe.",
    "audio_too_long": "The recording was longer than the allowed length.",
    "audio_corrupt": "The recording could not be read. It may be damaged.",
    "audio_unsupported": "The recording is not in a supported audio format.",
    "audio_missing": "The audio file is no longer available on the server.",
    "decoder_unavailable": "The server's audio tools are unavailable right now. Please try again later.",
    "rate_limited": "The transcription service is busy. Please try again shortly.",
    "provider_timeout": "The transcription service took too long. Please try again.",
    "provider_unreachable": "The transcription service could not be reached. Please try again.",
    "provider_error": "The transcription service had a problem. Please try again.",
    "provider_bad_response": "The transcription service returned an unreadable answer. Please try again.",
    "provider_auth": "Transcription is not configured correctly on the server.",
    "provider_not_configured": "Transcription is not configured correctly on the server.",
    "provider_not_installed": "Transcription is not configured correctly on the server.",
    "provider_rejected_audio": "The transcription service could not accept this recording.",
    "task_timeout": "Transcription took too long. Please try again.",
    "internal_error": "An unexpected error occurred while transcribing.",
}


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes
    return moment


def can_retry(response: CandidateResponse, settings: Settings) -> bool:
    """A recording can be (re)queued if it is failed, never dispatched, or stuck, and its audio still exists."""
    if response.transcription_attempts >= settings.transcription_max_attempts:
        return False
    status = response.transcription_status
    started = _aware(response.transcription_started_at)
    stuck = (
        status == TranscriptionStatus.PROCESSING
        and started is not None
        and datetime.now(timezone.utc) - started > timedelta(minutes=settings.transcription_stuck_minutes)
    )
    never_dispatched = status == TranscriptionStatus.PENDING and response.celery_task_id is None
    if not (status == TranscriptionStatus.FAILED or never_dispatched or stuck):
        return False
    return audio_intake.find_audio_path(response.id, settings.audio_temp_dir) is not None


def build_view(response: CandidateResponse, settings: Settings) -> TranscriptionView:
    completed = response.transcription_status == TranscriptionStatus.COMPLETED
    code = response.transcription_error if response.transcription_status == TranscriptionStatus.FAILED else None
    done_at = _aware(response.transcription_completed_at)
    return TranscriptionView(
        response_id=response.id,
        question_id=response.question_id,
        status=response.transcription_status.value,
        task_id=response.celery_task_id,
        transcript=response.transcript if completed else None,
        language=response.transcript_language if completed else None,
        duration_seconds=response.audio_duration_seconds if completed else None,
        provider=response.transcription_provider if completed else None,
        no_speech_detected=bool(response.no_speech_detected) if completed else False,
        error_code=code,
        error_message=(ERROR_MESSAGES.get(code, "Transcription failed.") if code else None),
        attempts=response.transcription_attempts,
        can_retry=can_retry(response, settings),
        completed_at=done_at.isoformat() if (completed and done_at) else None,
    )


def _session_or_404(db: Session, session_id: uuid.UUID) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found.")
    return session


def _response_or_404(db: Session, session_id: uuid.UUID, response_id: uuid.UUID) -> CandidateResponse:
    _session_or_404(db, session_id)
    response = db.get(CandidateResponse, response_id)
    if response is None or response.session_id != session_id:  # a response id from another session is "not found"
        raise HTTPException(status_code=404, detail="Answer not found in this session.")
    return response


def list_transcriptions(db: Session, settings: Settings, session_id: uuid.UUID) -> list[TranscriptionView]:
    _session_or_404(db, session_id)
    rows = db.scalars(
        sa.select(CandidateResponse).where(CandidateResponse.session_id == session_id).order_by(CandidateResponse.created_at, CandidateResponse.id)
    ).all()
    return [build_view(row, settings) for row in rows]


def get_transcription(db: Session, settings: Settings, session_id: uuid.UUID, response_id: uuid.UUID) -> TranscriptionView:
    return build_view(_response_or_404(db, session_id, response_id), settings)


def retry_transcription(db: Session, settings: Settings, session_id: uuid.UUID, response_id: uuid.UUID) -> TranscriptionView:
    response = _response_or_404(db, session_id, response_id)
    if not can_retry(response, settings):
        raise HTTPException(status_code=409, detail="This answer cannot be re-queued right now.")

    # Reset so that dispatch_transcription() issues a NEW task id. Guarded by the status we just checked.
    result = db.execute(
        sa.update(CandidateResponse)
        .where(
            CandidateResponse.id == response.id,
            CandidateResponse.transcription_status == response.transcription_status,
            CandidateResponse.celery_task_id.is_(response.celery_task_id) if response.celery_task_id is None
            else CandidateResponse.celery_task_id == response.celery_task_id,
        )
        .values(
            transcription_status=TranscriptionStatus.PENDING,
            celery_task_id=None,
            transcription_error=None,
            transcription_completed_at=None,
        )
    )
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="This answer was just updated; please check its status again.")
    dispatch_transcription(response.id)
    db.expire_all()
    return build_view(db.get(CandidateResponse, response.id), settings)
