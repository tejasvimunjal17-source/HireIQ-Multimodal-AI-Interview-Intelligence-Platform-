"""PDF report download (Day 6).

GET /api/reports/{session_id}/pdf   Authorization: Bearer <REPORT_ACCESS_TOKEN>

The existing API has no user accounts and the candidate knows their own session id, so the session id alone must NOT
unlock an evaluation (it contains the recommendation). Access therefore needs a shared server-side token; with no token
configured the endpoint is disabled (503). This is a stop-gap until real hiring-manager authentication exists.
The PDF is generated on request from stored data and is not saved anywhere (nothing to clean up, no duplicates).
"""

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.schemas.health import ErrorResponse
from app.services.reporting.loader import load_report_data
from app.services.reporting.pdf import render_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])


def require_report_access(authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> None:
    token = settings.report_access_token
    if token is None:
        raise HTTPException(status_code=503, detail="Manager access is disabled: REPORT_ACCESS_TOKEN is not configured on the server.")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.strip().encode(), token.get_secret_value().encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing access token.", headers={"WWW-Authenticate": "Bearer"})


@router.get(
    "/{session_id}/pdf",
    response_class=Response,
    dependencies=[Depends(require_report_access)],  # runs first: an unauthorised caller learns nothing about the session
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The evaluation report as a PDF download."},
        401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
    },
)
def download_report(session_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Candidate Interview Evaluation Report for ONE session (PDF)."""
    data = load_report_data(db, session_id)
    pdf = render_report(data)
    logger.info("Report generated session_id=%s bytes=%d", session_id, len(pdf))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="hireiq-evaluation-{session_id}.pdf"',  # no candidate name in the file name
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
