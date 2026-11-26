"""SQLAlchemy models, relationships and constraints.

Run against SQLite (stand-in for PostgreSQL) with foreign keys enabled.
Real PostgreSQL behaviour is checked by test_integration_services.py in CI.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.models import (
    Base, Candidate, CandidateResponse, Evaluation, Interview, InterviewSession,
    InterviewType, Question, QuestionType, Recommendation, Report, SessionStatus, TranscriptionStatus,
)

EXPECTED_TABLES = {
    "candidates", "interviews", "questions", "interview_sessions",
    "candidate_responses", "evaluations", "reports",
}


def build_graph(db):
    candidate = Candidate(full_name="Test Candidate", email="test@example.com")
    interview = Interview(title="Backend Interview", rubric_name="default", interview_type=InterviewType.MIXED)
    interview.questions = [
        Question(position=1, text="Explain REST.", question_type=QuestionType.TECHNICAL),
        Question(position=2, text="Tell me about a conflict.", question_type=QuestionType.BEHAVIORAL),
    ]
    session = InterviewSession(candidate=candidate, interview=interview)
    response = CandidateResponse(session=session, question=interview.questions[0], transcript="fake transcript")
    response.evaluation = Evaluation(
        overall_score=82.5, criteria_scores={"accuracy": 4}, explanation="ok",
        llm_provider="test", llm_model="test-model", rubric_name="default",
    )
    session.report = Report(overall_score=82.5, recommendation=Recommendation.PROCEED)
    db.add_all([candidate, interview, session, response])
    db.commit()
    return candidate, interview, session, response


def test_all_seven_tables_are_defined():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_every_table_has_uuid_pk_and_timestamps(table):
    columns = Base.metadata.tables[table].c
    assert "id" in columns and "created_at" in columns and "updated_at" in columns
    assert list(Base.metadata.tables[table].primary_key.columns)[0].name == "id"


def test_relationships_round_trip(db_session):
    candidate, interview, session, response = build_graph(db_session)
    db_session.expire_all()
    loaded = db_session.get(InterviewSession, session.id)
    assert loaded.candidate.email == "test@example.com"
    assert loaded.interview.title == "Backend Interview"
    assert [q.position for q in loaded.interview.questions] == [1, 2]
    assert loaded.responses[0].evaluation.overall_score == 82.5
    assert loaded.responses[0].question.text == "Explain REST."
    assert loaded.report.recommendation is Recommendation.PROCEED
    assert candidate.sessions == [loaded]


def test_defaults_and_server_generated_values(db_session):
    _, interview, session, response = build_graph(db_session)
    db_session.refresh(session)
    db_session.refresh(response)
    assert isinstance(session.id, uuid.UUID)
    assert session.status is SessionStatus.CREATED
    assert response.transcription_status is TranscriptionStatus.PENDING
    assert interview.is_active is True
    assert session.created_at is not None and session.updated_at is not None


def test_enums_are_stored_as_plain_strings(db_session, sqlite_engine):
    build_graph(db_session)
    with sqlite_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT status FROM interview_sessions")).scalar() == "created"
        assert conn.execute(sa.text("SELECT recommendation FROM reports")).scalar() == "proceed"


def test_candidate_email_must_be_unique(db_session):
    db_session.add(Candidate(full_name="A", email="same@example.com"))
    db_session.commit()
    db_session.add(Candidate(full_name="B", email="same@example.com"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_question_position_unique_within_interview(db_session):
    interview = Interview(title="T", rubric_name="r")
    interview.questions = [
        Question(position=1, text="a", question_type=QuestionType.TECHNICAL),
        Question(position=1, text="b", question_type=QuestionType.TECHNICAL),
    ]
    db_session.add(interview)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_one_session_per_candidate_per_interview(db_session):
    candidate, interview, *_ = build_graph(db_session)
    db_session.add(InterviewSession(candidate_id=candidate.id, interview_id=interview.id))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_one_response_per_question_per_session(db_session):
    _, interview, session, _ = build_graph(db_session)
    db_session.add(CandidateResponse(session_id=session.id, question_id=interview.questions[0].id))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_one_evaluation_per_response(db_session):
    *_, response = build_graph(db_session)
    db_session.add(Evaluation(
        response_id=response.id, overall_score=50, criteria_scores={}, explanation="x",
        llm_provider="t", llm_model="m", rubric_name="r",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("bad_score", [-1, 100.5])
def test_score_range_check_constraint(db_session, bad_score):
    *_, response = build_graph(db_session)
    other = CandidateResponse(session_id=response.session_id, question_id=response.session.interview.questions[1].id)
    db_session.add(other)
    db_session.flush()
    db_session.add(Evaluation(
        response_id=other.id, overall_score=bad_score, criteria_scores={}, explanation="x",
        llm_provider="t", llm_model="m", rubric_name="r",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_keys_are_enforced(db_session):
    db_session.add(Question(interview_id=uuid.uuid4(), position=1, text="x", question_type=QuestionType.TECHNICAL))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_candidate_removes_their_sessions_responses_evaluations_and_reports(db_session):
    candidate, *_ = build_graph(db_session)
    db_session.delete(candidate)
    db_session.commit()
    for model in (InterviewSession, CandidateResponse, Evaluation, Report):
        assert db_session.scalar(sa.select(sa.func.count()).select_from(model)) == 0
    # The interview template itself must survive.
    assert db_session.scalar(sa.select(sa.func.count()).select_from(Interview)) == 1


def test_expected_indexes_exist(sqlite_engine):
    inspector = sa.inspect(sqlite_engine)
    email_index = next(i for i in inspector.get_indexes("candidates") if i["name"] == "ix_candidates_email")
    assert email_index["unique"]
    session_indexes = {i["name"] for i in inspector.get_indexes("interview_sessions")}
    assert {"ix_interview_sessions_candidate_id", "ix_interview_sessions_status"} <= session_indexes
