"""Candidate interview API: sessions and audio upload. Runs on the SQLite stand-in."""

import re
import uuid

import pytest
import sqlalchemy as sa

from app.models import Candidate, CandidateResponse, Interview, InterviewSession, Question, QuestionType
from app.services.demo_seed import DEMO_QUESTIONS, seed_demo_interview

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 256
UUID_FILE = re.compile(r"^[0-9a-f-]{36}\.webm$")


@pytest.fixture
def interview_id(session_factory, api_client):
    with session_factory() as db:
        interview, _ = seed_demo_interview(db)
        return str(interview.id)


def start(client, interview_id, email="cand@example.com", **overrides):
    body = {"interview_id": interview_id, "candidate_name": "Test Candidate", "candidate_email": email, "consent": True}
    body.update(overrides)
    return client.post("/api/sessions", json=body)


def upload(client, session_id, question_id, data=WEBM, ctype="audio/webm;codecs=opus", filename="answer.webm", **form):
    return client.post(
        f"/api/sessions/{session_id}/responses",
        data={"question_id": question_id, **form},
        files={"audio": (filename, data, ctype)},
    )


@pytest.fixture
def session(api_client, interview_id):
    response = start(api_client, interview_id)
    assert response.status_code == 201
    return response.json()


# ---------- listing ----------
def test_list_returns_active_interviews_with_question_count(api_client, interview_id):
    body = api_client.get("/api/interviews").json()
    assert len(body) == 1
    assert body[0]["id"] == interview_id
    assert body[0]["question_count"] == len(DEMO_QUESTIONS)


def test_list_hides_inactive_and_empty_interviews(api_client, interview_id, session_factory):
    with session_factory() as db:
        db.add(Interview(title="Inactive", rubric_name="r", is_active=False,
                         questions=[Question(position=1, text="q", question_type=QuestionType.TECHNICAL)]))
        db.add(Interview(title="No questions", rubric_name="r"))
        db.commit()
    assert [i["id"] for i in api_client.get("/api/interviews").json()] == [interview_id]


@pytest.mark.parametrize("limit", [0, 51])
def test_list_limit_is_bounded(api_client, limit):
    assert api_client.get(f"/api/interviews?limit={limit}").status_code == 422


# ---------- starting a session ----------
def test_start_session_returns_ordered_questions_without_rubric_data(api_client, interview_id):
    body = start(api_client, interview_id).json()
    assert body["status"] == "created"
    assert [q["position"] for q in body["questions"]] == [1, 2, 3, 4]
    assert set(body["questions"][0]) == {"id", "position", "text", "question_type", "time_limit_seconds"}
    assert body["answered_question_ids"] == []


def test_start_session_stores_candidate_with_consent_and_normalized_email(api_client, interview_id, session_factory):
    start(api_client, interview_id, email="  Mixed.Case@Example.COM ")
    with session_factory() as db:
        candidate = db.scalar(sa.select(Candidate))
        assert candidate.email == "mixed.case@example.com"
        assert candidate.consent_given_at is not None


@pytest.mark.parametrize("override", [
    {"consent": False}, {"candidate_email": "not-an-email"}, {"candidate_name": "   "}, {"candidate_name": ""},
])
def test_start_session_validates_input(api_client, interview_id, override):
    assert start(api_client, interview_id, **override).status_code == 422


def test_start_session_unknown_interview_is_404(api_client):
    assert start(api_client, str(uuid.uuid4())).status_code == 404


def test_same_email_cannot_start_the_same_interview_twice(api_client, interview_id):
    assert start(api_client, interview_id).status_code == 201
    assert start(api_client, interview_id).status_code == 409


def test_get_session_and_errors(api_client, session):
    assert api_client.get(f"/api/sessions/{session['session_id']}").json()["session_id"] == session["session_id"]
    assert api_client.get(f"/api/sessions/{uuid.uuid4()}").status_code == 404
    assert api_client.get("/api/sessions/not-a-uuid").status_code == 422


# ---------- uploading audio ----------
def test_upload_stores_audio_privately_and_creates_pending_response(api_client, session, audio_dir, session_factory):
    qid = session["questions"][0]["id"]
    response = upload(api_client, session["session_id"], qid, duration_seconds="12.5")
    assert response.status_code == 201
    receipt = response.json()
    assert receipt["transcription_status"] == "pending"
    assert receipt["size_bytes"] == len(WEBM)
    assert receipt["question_id"] == qid
    assert (audio_dir / f"{receipt['response_id']}.webm").read_bytes() == WEBM

    with session_factory() as db:
        row = db.get(CandidateResponse, uuid.UUID(receipt["response_id"]))
        assert row.audio_duration_seconds == 12.5
        assert row.transcript is None
        assert db.get(InterviewSession, uuid.UUID(session["session_id"])).status.value == "in_progress"
    assert api_client.get(f"/api/sessions/{session['session_id']}").json()["answered_question_ids"] == [qid]


def test_browser_supplied_filename_is_never_used(api_client, session, audio_dir):
    upload(api_client, session["session_id"], session["questions"][0]["id"], filename="../../etc/passwd.webm")
    names = [p.name for p in audio_dir.iterdir()]
    assert len(names) == 1 and UUID_FILE.match(names[0])
    assert not (audio_dir.parent.parent / "etc").exists()


def test_unsupported_type_is_rejected_and_nothing_is_stored(api_client, session, audio_dir):
    r = upload(api_client, session["session_id"], session["questions"][0]["id"], data=b"hi", ctype="text/plain")
    assert r.status_code == 415
    assert not audio_dir.exists() or not list(audio_dir.iterdir())


def test_spoofed_audio_is_rejected(api_client, session, audio_dir):
    r = upload(api_client, session["session_id"], session["questions"][0]["id"], data=b"<script>alert(1)</script>")
    assert r.status_code == 415


def test_empty_audio_is_rejected(api_client, session):
    assert upload(api_client, session["session_id"], session["questions"][0]["id"], data=b"").status_code == 400


def test_oversized_audio_is_rejected_by_streaming_check(api_client, session, audio_dir, monkeypatch):
    monkeypatch.setenv("AUDIO_MAX_UPLOAD_MB", "1")
    from app.core.config import get_settings
    get_settings.cache_clear()
    big = WEBM + b"\x00" * (1024 * 1024)  # just over 1 MB, under the middleware's multipart allowance
    r = upload(api_client, session["session_id"], session["questions"][0]["id"], data=big)
    assert r.status_code == 413
    assert not list(audio_dir.iterdir())


def test_hugely_oversized_request_is_rejected_by_content_length_check(api_client, session, monkeypatch):
    monkeypatch.setenv("AUDIO_MAX_UPLOAD_MB", "1")
    from app.core.config import get_settings
    get_settings.cache_clear()
    r = upload(api_client, session["session_id"], session["questions"][0]["id"], data=WEBM + b"\x00" * (3 * 1024 * 1024))
    assert r.status_code == 413


def test_negative_duration_is_rejected(api_client, session):
    assert upload(api_client, session["session_id"], session["questions"][0]["id"], duration_seconds="-3").status_code == 422


def test_question_from_another_interview_is_rejected(api_client, session, session_factory):
    with session_factory() as db:
        other = Interview(title="Other", rubric_name="r",
                          questions=[Question(position=1, text="x", question_type=QuestionType.TECHNICAL)])
        db.add(other)
        db.commit()
        foreign_question = str(other.questions[0].id)
    assert upload(api_client, session["session_id"], foreign_question).status_code == 404
    assert upload(api_client, session["session_id"], str(uuid.uuid4())).status_code == 404


def test_unknown_session_is_404(api_client, session):
    assert upload(api_client, str(uuid.uuid4()), session["questions"][0]["id"]).status_code == 404


def test_answering_the_same_question_twice_is_409_and_keeps_one_file(api_client, session, audio_dir):
    qid = session["questions"][0]["id"]
    assert upload(api_client, session["session_id"], qid).status_code == 201
    assert upload(api_client, session["session_id"], qid).status_code == 409
    assert len(list(audio_dir.iterdir())) == 1


def test_audio_is_not_reachable_through_any_public_url(api_client, session, audio_dir):
    receipt = upload(api_client, session["session_id"], session["questions"][0]["id"]).json()
    rid = receipt["response_id"]
    for path in (f"/audio/{rid}.webm", f"/static/{rid}.webm", f"/uploads/{rid}.webm",
                 f"/api/sessions/{session['session_id']}/responses/{rid}",
                 f"/api/sessions/{session['session_id']}/responses"):
        assert api_client.get(path).status_code in (404, 405)


@pytest.mark.mocked
def test_transcription_hook_is_called_once_with_response_id(api_client, session, monkeypatch):
    """MOCKED: spy on the Day 3 hook. Proves the integration point is wired, not that transcription works."""
    calls = []
    monkeypatch.setattr("app.services.session_service.dispatch_transcription", calls.append)
    receipt = upload(api_client, session["session_id"], session["questions"][0]["id"]).json()
    assert calls == [uuid.UUID(receipt["response_id"])]


@pytest.mark.mocked
def test_audio_file_is_removed_if_saving_to_the_database_fails(api_client, session, audio_dir, monkeypatch):
    """MOCKED: force the DB commit to fail after the file was written."""
    def failing_commit(self):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr("sqlalchemy.orm.Session.commit", failing_commit)
    with pytest.raises(RuntimeError):
        upload(api_client, session["session_id"], session["questions"][0]["id"])
    assert not list(audio_dir.iterdir())


# ---------- completing ----------
def test_complete_requires_all_questions_answered(api_client, session):
    sid = session["session_id"]
    upload(api_client, sid, session["questions"][0]["id"])
    r = api_client.post(f"/api/sessions/{sid}/complete")
    assert r.status_code == 409
    assert "3 question" in r.json()["detail"]


def test_full_flow_complete_then_locked(api_client, session):
    sid = session["session_id"]
    for q in session["questions"]:
        assert upload(api_client, sid, q["id"]).status_code == 201
    assert api_client.post(f"/api/sessions/{sid}/complete").json()["status"] == "submitted"
    assert api_client.post(f"/api/sessions/{sid}/complete").json()["status"] == "submitted"  # idempotent
    # No more answers after submission.
    assert upload(api_client, sid, session["questions"][0]["id"]).status_code == 409
    assert api_client.get(f"/api/sessions/{sid}").json()["status"] == "submitted"
