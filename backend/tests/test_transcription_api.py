"""Upload -> task dispatch -> status/retry endpoints. The Celery broker is a MOCK (a list); the API,
database and file handling are real code on the SQLite stand-in."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.models import CandidateResponse, TranscriptionStatus
from app.services import audio_intake, transcription_dispatch
from app.services.demo_seed import seed_demo_interview
from tests.test_interview_api import WEBM, start, upload


@pytest.fixture
def interview_id(session_factory, api_client):
    with session_factory() as db:
        return str(seed_demo_interview(db)[0].id)


@pytest.fixture
def answered(api_client, interview_id):
    """A started session with the first question answered. Returns (session_view, receipt)."""
    view = start(api_client, interview_id).json()
    receipt = upload(api_client, view["session_id"], view["questions"][0]["id"]).json()
    return view, receipt


def put_state(session_factory, response_id, **values):
    if not values:
        return
    with session_factory() as db:
        db.execute(sa.update(CandidateResponse).where(CandidateResponse.id == uuid.UUID(response_id)).values(**values))
        db.commit()


def url(view, receipt, suffix=""):
    return f"/api/sessions/{view['session_id']}/responses/{receipt['response_id']}/transcription{suffix}"


# ---------------------------------------------------------------- dispatch after upload
def test_upload_returns_a_task_id_and_queues_exactly_one_task(answered, enqueued, session_factory):
    _, receipt = answered
    assert receipt["task_id"] and len(enqueued) == 1
    assert enqueued[0] == (uuid.UUID(receipt["response_id"]), receipt["task_id"])
    with session_factory() as db:
        row = db.get(CandidateResponse, uuid.UUID(receipt["response_id"]))
        assert row.celery_task_id == receipt["task_id"] and row.transcription_status == TranscriptionStatus.PENDING


def test_dispatching_the_same_recording_twice_queues_one_task(answered, enqueued):
    _, receipt = answered
    again = transcription_dispatch.dispatch_transcription(uuid.UUID(receipt["response_id"]))
    assert again == receipt["task_id"] and len(enqueued) == 1


def test_upload_still_succeeds_if_the_queue_is_down_and_can_be_recovered(api_client, interview_id, monkeypatch, enqueued):
    def broker_down(response_id, task_id):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("app.services.transcription_dispatch._enqueue", broker_down)
    view = start(api_client, interview_id).json()
    response = upload(api_client, view["session_id"], view["questions"][0]["id"])
    receipt = response.json()
    assert response.status_code == 201 and receipt["task_id"] is None

    status = api_client.get(url(view, receipt)).json()
    assert status["status"] == "pending" and status["task_id"] is None and status["can_retry"] is True

    monkeypatch.setattr("app.services.transcription_dispatch._enqueue", lambda rid, tid: enqueued.append((rid, tid)))
    retried = api_client.post(url(view, receipt, "/retry"))
    assert retried.status_code == 202 and retried.json()["task_id"] and len(enqueued) == 1


def test_dispatch_never_raises_even_if_the_database_is_broken(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.transcription_dispatch.get_session_factory", boom)
    assert transcription_dispatch.dispatch_transcription(uuid.uuid4()) is None


# ---------------------------------------------------------------- status endpoints
def test_pending_status(api_client, answered):
    view, receipt = answered
    body = api_client.get(url(view, receipt)).json()
    assert body["status"] == "pending" and body["transcript"] is None and body["task_id"] == receipt["task_id"]
    assert body["can_retry"] is False and body["attempts"] == 0


def test_transcript_is_hidden_until_completed(api_client, answered, session_factory):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], transcription_status=TranscriptionStatus.PROCESSING,
              transcript="partial secret text", transcript_language="en")
    body = api_client.get(url(view, receipt)).json()
    assert body["status"] == "processing" and body["transcript"] is None and body["language"] is None


def test_completed_status_includes_the_result(api_client, answered, session_factory):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], transcription_status=TranscriptionStatus.COMPLETED,
              transcript="Hello there", transcript_language="en", audio_duration_seconds=3.2,
              transcription_provider="mock", transcription_attempts=1,
              transcription_completed_at=datetime.now(timezone.utc))
    body = api_client.get(url(view, receipt)).json()
    assert (body["status"], body["transcript"], body["language"]) == ("completed", "Hello there", "en")
    assert body["duration_seconds"] == 3.2 and body["provider"] == "mock" and body["completed_at"]
    assert body["can_retry"] is False and body["error_code"] is None


def test_failed_status_has_a_friendly_message(api_client, answered, session_factory):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], transcription_status=TranscriptionStatus.FAILED,
              transcription_error="audio_corrupt")
    audio_intake.delete_audio(uuid.UUID(receipt["response_id"]), str(audio_dir_of(api_client)))
    body = api_client.get(url(view, receipt)).json()
    assert body["status"] == "failed" and body["error_code"] == "audio_corrupt"
    assert "damaged" in body["error_message"] and body["can_retry"] is False  # audio is gone


def audio_dir_of(client):
    from app.core.config import get_settings
    return get_settings().audio_temp_dir


def test_failed_answer_with_retained_audio_can_be_retried(api_client, answered, session_factory, enqueued):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], transcription_status=TranscriptionStatus.FAILED,
              transcription_error="provider_timeout", transcription_attempts=3)
    assert api_client.get(url(view, receipt)).json()["can_retry"] is True
    response = api_client.post(url(view, receipt, "/retry"))
    body = response.json()
    assert response.status_code == 202 and body["status"] == "pending" and body["error_code"] is None
    assert body["task_id"] != receipt["task_id"] and len(enqueued) == 2
    assert enqueued[1][1] == body["task_id"]


@pytest.mark.parametrize("state, reason", [
    ({}, "pending with a queued task"),
    ({"transcription_status": TranscriptionStatus.PROCESSING, "transcription_started_at": datetime.now(timezone.utc)}, "recently started"),
    ({"transcription_status": TranscriptionStatus.COMPLETED}, "already completed"),
    ({"transcription_status": TranscriptionStatus.FAILED, "transcription_attempts": 6}, "attempt limit reached"),
])
def test_retry_is_refused_when_not_appropriate(api_client, answered, session_factory, enqueued, state, reason):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], **state)
    response = api_client.post(url(view, receipt, "/retry"))
    assert response.status_code == 409, reason
    assert len(enqueued) == 1


def test_a_stuck_processing_answer_can_be_requeued(api_client, answered, session_factory, enqueued):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], transcription_status=TranscriptionStatus.PROCESSING,
              transcription_started_at=datetime.now(timezone.utc) - timedelta(minutes=45))
    assert api_client.post(url(view, receipt, "/retry")).status_code == 202
    assert len(enqueued) == 2


def test_retry_needs_the_audio_to_still_exist(api_client, answered, session_factory):
    view, receipt = answered
    put_state(session_factory, receipt["response_id"], transcription_status=TranscriptionStatus.FAILED)
    audio_intake.delete_audio(uuid.UUID(receipt["response_id"]), audio_dir_of(api_client))
    assert api_client.post(url(view, receipt, "/retry")).status_code == 409


def test_list_shows_every_answer_of_the_session(api_client, answered):
    view, receipt = answered
    second = upload(api_client, view["session_id"], view["questions"][1]["id"]).json()
    items = api_client.get(f"/api/sessions/{view['session_id']}/transcriptions").json()
    assert {i["response_id"] for i in items} == {receipt["response_id"], second["response_id"]}
    assert all(i["status"] == "pending" for i in items)


def test_unknown_ids_are_404_and_other_sessions_cannot_peek(api_client, answered, interview_id):
    view, receipt = answered
    assert api_client.get(f"/api/sessions/{uuid.uuid4()}/transcriptions").status_code == 404
    assert api_client.get(f"/api/sessions/{view['session_id']}/responses/{uuid.uuid4()}/transcription").status_code == 404
    other = start(api_client, interview_id, email="other@example.com").json()
    assert api_client.get(f"/api/sessions/{other['session_id']}/responses/{receipt['response_id']}/transcription").status_code == 404
    assert api_client.post(f"/api/sessions/{other['session_id']}/responses/{receipt['response_id']}/transcription/retry").status_code == 404


def test_new_endpoints_are_documented(api_client):
    paths = api_client.get("/openapi.json").json()["paths"]
    assert "/api/sessions/{session_id}/transcriptions" in paths
    assert "/api/sessions/{session_id}/responses/{response_id}/transcription" in paths
    assert "/api/sessions/{session_id}/responses/{response_id}/transcription/retry" in paths
