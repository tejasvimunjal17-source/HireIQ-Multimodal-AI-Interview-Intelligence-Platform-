"""Day 9, group: END-TO-END WORKFLOW through the real FastAPI app, SQLAlchemy models and the real Celery task code.

STATUS: WRITTEN, NOT EXECUTED in the build sandbox (SQLAlchemy, FastAPI and Celery cannot be installed offline). It has
never run, so it may need small adjustments the first time it does. Do not count it as passed.
Run it with:   cd backend && pytest tests/test_day9_workflow_e2e.py -v

WHAT IS REAL AND WHAT IS NOT (per the Day 9 rules)
  real code : HTTP API (TestClient), request validation, auth dependency, SQLAlchemy models + queries, audio intake,
              audio processing of a real WAV file, the two Celery TASK functions (run in-process with Task.apply),
              the evaluation pipeline with the YAML rubric, NLP enrichment (spaCy/VADER if installed, else partial),
              session status coordination, dashboard queries, PDF rendering.
  stand-ins : the database is SQLite in memory (not PostgreSQL); the Celery broker is a list (no Redis, no worker
              process); transcription uses the MOCK provider (fixed placeholder text, no Whisper); evaluation uses the
              MOCK provider (no LLM). Therefore this is NOT a verification of PostgreSQL, Redis, Whisper or a real LLM.
Those live-service paths are in tests/test_integration_services.py (RUN_INTEGRATION=1) and tests/test_openai_real.py.
"""

import io
import uuid

import pytest

from app.core.config import get_settings
from app.models import CandidateResponse, Evaluation, EvaluationStatus, InterviewSession, SessionStatus, TranscriptionStatus
from app.services.demo_seed import seed_demo_interview
from app.workers.evaluation_tasks import evaluate_response
from app.workers.transcription_tasks import transcribe_response
from tests.dashboard_builders import AUTH, TOKEN
from tests.helpers_audio import wav_bytes
from tests.test_interview_api import start, upload

pypdf = pytest.importorskip("pypdf")


@pytest.fixture
def stack(monkeypatch, session_factory, api_client, evaluation_enqueued, enqueued):
    """Mock providers, manager token set, task code pointed at the SQLite stand-in."""
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "mock")
    monkeypatch.setenv("EVALUATION_PROVIDER", "mock")
    monkeypatch.setenv("REPORT_ACCESS_TOKEN", TOKEN)
    get_settings.cache_clear()
    monkeypatch.setattr("app.workers.transcription_tasks.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.workers.evaluation_tasks.get_session_factory", lambda: session_factory)
    with session_factory() as db:
        interview, _ = seed_demo_interview(db)
        interview_id = str(interview.id)
    return type("Stack", (), {"client": api_client, "interview_id": interview_id, "factory": session_factory,
                              "evaluation_queue": evaluation_enqueued})()


def answer_all(stack, view):
    """Upload a real WAV for every question, then run the transcription task and the evaluation task for each."""
    for question in view["questions"]:
        receipt = upload(stack.client, view["session_id"], question["id"], data=wav_bytes(1.0, rate=16000, channels=1),
                         ctype="audio/wav", filename="answer.wav")
        assert receipt.status_code == 201, receipt.text
        body = receipt.json()
        done = transcribe_response.apply(args=[body["response_id"]], task_id=body["task_id"])
        assert done.result["status"] == "completed", done.result
    # the transcription task handed every answer to evaluation (broker is a list here)
    assert len(stack.evaluation_queue) == len(view["questions"])
    for response_id, task_id in list(stack.evaluation_queue):
        assert evaluate_response.apply(args=[str(response_id)], task_id=task_id).result["status"] == "evaluated"


# ------------------------------------------------------------------ A + B: candidate and evaluation workflow
def test_full_workflow_from_interview_list_to_evaluated_session(stack):
    client = stack.client
    listing = client.get("/api/interviews")
    assert listing.status_code == 200 and listing.json()[0]["id"] == stack.interview_id

    view = start(client, stack.interview_id).json()
    assert view["status"] in {"created", "in_progress"} and len(view["questions"]) == 4
    assert "rubric" not in str(view).lower() and "recommend" not in str(view).lower()

    answer_all(stack, view)

    status = client.get(f"/api/sessions/{view['session_id']}/transcriptions").json()
    assert {t["status"] for t in status} == {"completed"} and all(t["transcript"] for t in status)

    done = client.post(f"/api/sessions/{view['session_id']}/complete")
    assert done.status_code == 200 and done.json()["status"] == "evaluated"

    with stack.factory() as db:
        session = db.get(InterviewSession, uuid.UUID(view["session_id"]))
        assert session.status == SessionStatus.EVALUATED
        rows = db.query(CandidateResponse).filter_by(session_id=session.id).all()
        assert all(r.transcription_status == TranscriptionStatus.COMPLETED and r.evaluation_status == EvaluationStatus.COMPLETED for r in rows)
        evaluations = db.query(Evaluation).all()
        assert len(evaluations) == 4 and all(0 <= e.overall_score <= 100 and e.criteria_scores and e.llm_provider == "mock" for e in evaluations)
        assert all(e.nlp_enrichment is not None for e in evaluations)  # advisory data stored beside, never in, the score


def test_a_session_cannot_be_completed_while_questions_are_unanswered(stack):
    view = start(stack.client, stack.interview_id).json()
    assert stack.client.post(f"/api/sessions/{view['session_id']}/complete").status_code == 409


# ------------------------------------------------------------------ C: reports
def test_pdf_requires_the_token_and_contains_the_evaluation(stack):
    view = start(stack.client, stack.interview_id, candidate_name="Asha Verma").json()
    answer_all(stack, view)
    stack.client.post(f"/api/sessions/{view['session_id']}/complete")
    url = f"/api/reports/{view['session_id']}/pdf"

    assert stack.client.get(url).status_code == 401
    assert stack.client.get(url, headers={"Authorization": "Bearer wrong-token-wrong-token"}).status_code == 401

    response = stack.client.get(url, headers=AUTH)
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-") and "Asha Verma" not in response.headers["content-disposition"]
    text = " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(response.content)).pages)
    assert "Asha Verma" in text and "cand@example.com" not in text and "ADVISORY" in text


def test_report_for_a_session_without_evaluation_is_a_clear_409_and_unknown_session_a_404(stack):
    view = start(stack.client, stack.interview_id).json()
    assert stack.client.get(f"/api/reports/{view['session_id']}/pdf", headers=AUTH).status_code == 409
    assert stack.client.get(f"/api/reports/{uuid.uuid4()}/pdf", headers=AUTH).status_code == 404


# ------------------------------------------------------------------ D: hiring manager workflow
def test_dashboard_is_consistent_with_stored_records_and_hides_restricted_fields(stack):
    client = stack.client
    for url in ("/api/dashboard/summary", "/api/dashboard/sessions"):
        assert client.get(url).status_code == 401

    view = start(client, stack.interview_id, candidate_name="Asha Verma", email="asha.private@example.com").json()
    answer_all(stack, view)
    client.post(f"/api/sessions/{view['session_id']}/complete")
    other = start(client, stack.interview_id, candidate_name="Ben Other", email="ben.private@example.com").json()  # in progress

    summary = client.get("/api/dashboard/summary", headers=AUTH).json()
    assert summary["total_sessions"] == 2 and summary["evaluated_sessions"] == 1

    listing = client.get("/api/dashboard/sessions", headers=AUTH, params={"search": "asha"}).json()
    assert listing["total"] == 1 and listing["items"][0]["session_id"] == view["session_id"]
    assert client.get("/api/dashboard/sessions", headers=AUTH, params={"status": "evaluated"}).json()["total"] == 1
    page = client.get("/api/dashboard/sessions", headers=AUTH, params={"page": 2, "page_size": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1 and other["session_id"] != ""

    detail = client.get(f"/api/dashboard/sessions/{view['session_id']}", headers=AUTH)
    assert detail.status_code == 200 and len(detail.json()["answers"]) == 4
    blob = detail.text + client.get("/api/dashboard/sessions", headers=AUTH).text
    assert "private@example.com" not in blob and ".wav" not in blob and "audio" not in blob.lower().replace("automatic", "")
    assert "MOCK TRANSCRIPT" not in blob  # transcripts are not part of the dashboard views


# ------------------------------------------------------------------ E: question bank and rubric workflow
def test_question_bank_creation_feeds_the_candidate_workflow(stack, monkeypatch, tmp_path):
    client = stack.client
    created = client.post("/api/question-bank/interviews", headers=AUTH,
                          json={"title": "Day 9 role", "rubric_name": "default", "interview_type": "technical"})
    assert created.status_code == 201 and created.json()["is_active"] is False
    interview_id = created.json()["id"]
    assert client.put(f"/api/question-bank/interviews/{interview_id}/active", headers=AUTH, json={"active": True}).status_code == 409  # no questions

    added = client.post(f"/api/question-bank/interviews/{interview_id}/questions", headers=AUTH, json={
        "text": "Explain how a database index speeds up reads.", "question_type": "technical", "category": "databases",
        "difficulty": "medium", "expected_skills": ["SQL", "indexing"]})
    assert added.status_code == 201
    bad = client.post(f"/api/question-bank/interviews/{interview_id}/questions", headers=AUTH,
                      json={"text": "short", "question_type": "technical"})
    assert bad.status_code == 422
    assert client.put(f"/api/question-bank/interviews/{interview_id}/active", headers=AUTH, json={"active": True}).status_code == 200

    filtered = client.get("/api/question-bank/questions", headers=AUTH, params={"category": "databases", "skill": "sql"}).json()
    assert filtered["total"] == 1 and filtered["items"][0]["rubric_key"] == "technical"

    view = start(client, interview_id).json()  # the existing candidate workflow works on a bank-created interview
    assert len(view["questions"]) == 1 and "databases" not in str(view) and "expected_skills" not in str(view)
    answer_all(stack, view)
    assert client.post(f"/api/sessions/{view['session_id']}/complete").json()["status"] == "evaluated"
