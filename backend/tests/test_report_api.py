"""Day 6: report loader and GET /api/reports/{session_id}/pdf (needs SQLAlchemy, FastAPI, pypdf; SQLite stand-in DB).

Written to run in CI; they could NOT be executed in the offline build sandbox (see docs/PROGRESS.md)."""

import io
import uuid

import pytest

pypdf = pytest.importorskip("pypdf")

from app.core.config import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    Candidate, CandidateResponse, Evaluation, EvaluationStatus, Interview, InterviewSession, Question, QuestionType,
    Recommendation, TranscriptionStatus,
)
from app.services.reporting.loader import load_report_data  # noqa: E402
from tests.report_samples import TK, evaluation  # noqa: E402

TOKEN = "unit-test-report-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("REPORT_ACCESS_TOKEN", TOKEN)
    get_settings.cache_clear()


def make_session(db, name="Asha Verma", evaluated=True, transcript="Threads share memory.", question_count=2):
    candidate = Candidate(full_name=name, email=f"{uuid.uuid4().hex[:8]}@example.com")
    interview = Interview(title="Backend Screening", rubric_name="default", questions=[
        Question(position=i + 1, text=f"Question {i + 1}?", question_type=QuestionType.TECHNICAL) for i in range(question_count)
    ])
    session = InterviewSession(candidate=candidate, interview=interview)
    response = CandidateResponse(
        session=session, question=interview.questions[0], transcription_status=TranscriptionStatus.COMPLETED,
        transcript=transcript, evaluation_status=EvaluationStatus.COMPLETED if evaluated else EvaluationStatus.PENDING,
    )
    db.add_all([candidate, interview, session, response])
    if evaluated:
        ev = evaluation()
        db.add(Evaluation(
            response=response, overall_score=ev["overall_score"], criteria_scores=ev["criteria_scores"], explanation=ev["explanation"],
            nlp_enrichment=ev["nlp_enrichment"], llm_provider="mock", llm_model="m", rubric_name="default",
            recommendation=Recommendation.PROCEED, evaluation_details=ev["evaluation_details"],
        ))
    db.commit()
    return session


def pdf_text(content: bytes) -> str:
    return " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(content)).pages)


# ------------------------------------------------------------------ loader
def test_loader_maps_stored_rows(db_session):
    session = make_session(db_session)
    data = load_report_data(db_session, session.id)
    assert data.candidate_name == "Asha Verma" and data.interview_title == "Backend Screening"
    assert len(data.answers) == 2  # both interview questions, in position order
    first, second = data.answers
    assert first.position == 1 and first.overall_score == 75.5 and first.recommendation == "proceed"
    assert [c.key for c in first.criteria] == TK
    assert second.answered is False and second.status_text.startswith("No answer")


def test_loader_unknown_session_is_404(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        load_report_data(db_session, uuid.uuid4())
    assert err.value.status_code == 404


def test_loader_without_any_evaluation_is_409(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        load_report_data(db_session, make_session(db_session, evaluated=False).id)
    assert err.value.status_code == 409


def test_loader_never_mixes_in_another_sessions_data(db_session):
    mine = make_session(db_session, name="Alice Mine", transcript="MY-WORDS")
    make_session(db_session, name="Bob Other", transcript="OTHER-WORDS")
    data = load_report_data(db_session, mine.id)
    blob = repr(data) + " ".join(a.transcript or "" for a in data.answers) + (data.candidate_name or "")
    assert "OTHER-WORDS" not in blob and "Bob" not in blob and "MY-WORDS" in blob


def test_loader_does_not_write_or_load_email(db_session):
    session = make_session(db_session)
    load_report_data(db_session, session.id)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert "example.com" not in repr(load_report_data(db_session, session.id))


def test_loader_does_not_log_candidate_text(db_session, caplog):
    caplog.set_level("DEBUG")
    session = make_session(db_session, name="Zed Secretname", transcript="SECRET-WORDS")
    load_report_data(db_session, session.id)
    assert "SECRET-WORDS" not in caplog.text and "Zed Secretname" not in caplog.text


# ------------------------------------------------------------------ endpoint
def test_download_returns_pdf_with_download_headers(api_client, db_session, token):
    session = make_session(db_session)
    response = api_client.get(f"/api/reports/{session.id}/pdf", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="hireiq-evaluation-{session.id}.pdf"'
    assert response.headers["cache-control"] == "no-store" and response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"%PDF-")
    assert "Asha" not in response.headers["content-disposition"]
    text = pdf_text(response.content)
    assert "Asha Verma" in text and "Candidate Interview Evaluation Report" in text and "75.5" in text


def test_unknown_session_is_404_with_error_body(api_client, token):
    response = api_client.get(f"/api/reports/{uuid.uuid4()}/pdf", headers=AUTH)
    assert response.status_code == 404 and response.json()["detail"] == "Interview session not found."


def test_session_without_evaluation_is_409_not_a_misleading_pdf(api_client, db_session, token):
    session = make_session(db_session, evaluated=False)
    response = api_client.get(f"/api/reports/{session.id}/pdf", headers=AUTH)
    assert response.status_code == 409 and response.headers["content-type"].startswith("application/json")


def test_invalid_session_id_is_422(api_client, token):
    assert api_client.get("/api/reports/not-a-uuid/pdf", headers=AUTH).status_code == 422


def test_missing_or_wrong_token_is_401(api_client, db_session, token):
    session = make_session(db_session)
    url = f"/api/reports/{session.id}/pdf"
    assert api_client.get(url).status_code == 401
    wrong = api_client.get(url, headers={"Authorization": "Bearer wrong-token-wrong-token"})
    assert wrong.status_code == 401 and wrong.headers["www-authenticate"] == "Bearer"
    assert api_client.get(url, headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401


def test_auth_is_checked_before_the_session_lookup(api_client, token):
    # an unauthorised caller must not learn whether a session exists
    assert api_client.get(f"/api/reports/{uuid.uuid4()}/pdf").status_code == 401


def test_endpoint_is_disabled_without_a_configured_token(api_client, db_session, monkeypatch):
    monkeypatch.delenv("REPORT_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    session = make_session(db_session)
    assert api_client.get(f"/api/reports/{session.id}/pdf", headers=AUTH).status_code == 503


def test_endpoint_stores_nothing_and_does_not_change_evaluations(api_client, db_session, token, tmp_path):
    from app.models import Report
    session = make_session(db_session)
    before = db_session.get(Evaluation, db_session.query(Evaluation).one().id).overall_score
    api_client.get(f"/api/reports/{session.id}/pdf", headers=AUTH)
    db_session.expire_all()
    assert db_session.query(Report).count() == 0
    assert db_session.query(Evaluation).one().overall_score == before


def test_endpoint_is_in_the_openapi_schema(api_client):
    paths = api_client.get("/openapi.json").json()["paths"]
    assert "get" in paths["/api/reports/{session_id}/pdf"]
