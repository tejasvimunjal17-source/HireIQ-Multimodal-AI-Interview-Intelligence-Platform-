"""Day 7: privacy guard on the dashboard response schemas (pure pydantic; runs without a database)."""

import uuid

import pytest

from app.schemas import dashboard as schemas

FORBIDDEN = ("email", "transcript", "audio", "task_id", "file_path", "api_key", "token", "segments")


def all_fields(model, seen=None):
    seen = seen if seen is not None else set()
    for name, field in model.model_fields.items():
        seen.add(name)
    return seen


@pytest.mark.parametrize("model", [schemas.SessionRow, schemas.SessionPage, schemas.DashboardSummary, schemas.SessionDetail, schemas.AnswerView, schemas.CriterionView])
def test_no_sensitive_field_names_in_any_dashboard_schema(model):
    for name in all_fields(model):
        assert not any(bad in name.lower() for bad in FORBIDDEN), f"{model.__name__}.{name}"


def test_missing_values_stay_none_not_zero():
    row = schemas.SessionRow(
        session_id=uuid.uuid4(), interview_id=uuid.uuid4(), interview_title="T", status="submitted", question_count=2,
        answered_count=0, evaluated_count=0, advice=schemas.AdviceCounts(),
    )
    dumped = row.model_dump()
    assert dumped["overall_score"] is None and dumped["candidate_name"] is None and dumped["recommendation"] is None


def test_recommendation_values_are_restricted_to_the_three_stored_ones():
    with pytest.raises(Exception):
        schemas.SessionRow(session_id=uuid.uuid4(), interview_id=uuid.uuid4(), interview_title="T", status="x", question_count=1,
                           answered_count=0, evaluated_count=0, advice=schemas.AdviceCounts(), recommendation="maybe")


def test_public_nlp_drops_internal_parts_and_keeps_what_the_ui_shows():
    from tests.report_samples import NLP
    nlp = {**NLP, "errors": {"spacy": "model path /srv/x missing"}, "models": {"spacy": "en_core_web_sm"}}
    out = schemas.public_nlp(nlp)
    assert "errors" not in out and "models" not in out and "schema_version" not in out
    assert "indicators" not in out["confidence"] and out["confidence"]["score"] == 0.71 and out["confidence"]["label"] == "high"
    assert out["sentiment"]["compound"] == 0.4 and out["keywords"][0]["text"] == "race condition"


def test_public_nlp_tolerates_missing_or_odd_input():
    assert schemas.public_nlp(None) is None and schemas.public_nlp("x") is None
    assert schemas.public_nlp({"status": "completed"}) == {"status": "completed"}
