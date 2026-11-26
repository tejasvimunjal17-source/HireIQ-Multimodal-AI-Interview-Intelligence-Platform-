"""Day 7: hiring-manager dashboard API (needs SQLAlchemy + FastAPI; SQLite stand-in DB).

Written to run in CI; NOT executed in the offline build sandbox (see docs/PROGRESS.md)."""

import uuid

import pytest

from app.core.config import get_settings
from app.models import Recommendation, SessionStatus
from tests.dashboard_builders import AUTH, TOKEN, make_interview, make_session


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("REPORT_ACCESS_TOKEN", TOKEN)
    get_settings.cache_clear()


def names(page):
    return [row["candidate_name"] for row in page["items"]]


def get(client, path, **params):
    return client.get(path, params=params, headers=AUTH)


# ---------------------------------------------------------------- access control
@pytest.mark.parametrize("path", ["/api/dashboard/summary", "/api/dashboard/sessions", f"/api/dashboard/sessions/{uuid.uuid4()}"])
def test_every_route_needs_the_token(api_client, path):
    assert api_client.get(path).status_code == 401
    assert api_client.get(path, headers={"Authorization": "Bearer wrong-wrong-wrong-wrong"}).status_code == 401


def test_dashboard_is_disabled_without_a_configured_token(api_client, monkeypatch):
    monkeypatch.delenv("REPORT_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    assert api_client.get("/api/dashboard/summary", headers=AUTH).status_code == 503


def test_unknown_session_is_404_only_after_authorisation(api_client):
    url = f"/api/dashboard/sessions/{uuid.uuid4()}"
    assert api_client.get(url).status_code == 401
    assert api_client.get(url, headers=AUTH).status_code == 404


# ---------------------------------------------------------------- empty database
def test_empty_database(api_client):
    s = get(api_client, "/api/dashboard/summary").json()
    assert s["total_sessions"] == 0 and s["average_score"] is None and s["scored_sessions"] == 0
    assert all(b["count"] == 0 for b in s["score_distribution"]) and len(s["score_distribution"]) == 5
    assert get(api_client, "/api/dashboard/sessions").json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


# ---------------------------------------------------------------- metrics
def test_summary_metrics_are_computed_from_stored_rows(api_client, db_session):
    iv = make_interview(db_session)
    make_session(db_session, iv, "A", SessionStatus.EVALUATED, scores=(80, 60))            # session score 70
    make_session(db_session, iv, "B", SessionStatus.EVALUATED, scores=(100,))             # 100
    make_session(db_session, iv, "C", SessionStatus.PROCESSING, scores=())                # no score
    make_session(db_session, iv, "D", SessionStatus.SUBMITTED)
    make_session(db_session, iv, "E", SessionStatus.IN_PROGRESS)
    make_session(db_session, iv, "F", SessionStatus.FAILED)
    s = get(api_client, "/api/dashboard/summary").json()
    assert s["total_sessions"] == 6
    assert s["by_status"] == {"created": 0, "in_progress": 1, "submitted": 1, "processing": 1, "evaluated": 2, "failed": 1}
    assert s["completed_interviews"] == 5 and s["awaiting_evaluation"] == 2 and s["evaluation_failed"] == 1 and s["evaluated_sessions"] == 2
    assert s["scored_sessions"] == 2 and s["average_score"] == pytest.approx(85.0)  # mean of 70 and 100, not of answers
    counts = {b["label"]: b["count"] for b in s["score_distribution"]}
    assert counts == {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 1, "80-100": 1}  # 100 is inside the last bucket


def test_stored_report_score_wins_over_the_average(api_client, db_session):
    iv = make_interview(db_session)
    make_session(db_session, iv, "A", scores=(80, 60), report=(55.5, Recommendation.REJECT))
    row = get(api_client, "/api/dashboard/sessions").json()["items"][0]
    assert row["overall_score"] == 55.5 and row["score_source"] == "stored_report" and row["recommendation"] == "reject"
    assert get(api_client, "/api/dashboard/summary").json()["average_score"] == 55.5


def test_unscored_session_has_null_score_never_zero(api_client, db_session):
    make_session(db_session, make_interview(db_session), "A", SessionStatus.SUBMITTED)
    row = get(api_client, "/api/dashboard/sessions").json()["items"][0]
    assert row["overall_score"] is None and row["score_source"] is None and row["recommendation"] is None
    assert row["evaluated_count"] == 0 and row["question_count"] == 2


def test_row_fields_and_advice_counts(api_client, db_session):
    make_session(db_session, make_interview(db_session, "Role X"), "Asha", scores=(80, 60), recs=(Recommendation.PROCEED, Recommendation.HOLD))
    row = get(api_client, "/api/dashboard/sessions").json()["items"][0]
    assert row["candidate_name"] == "Asha" and row["interview_title"] == "Role X" and row["overall_score"] == 70
    assert row["score_source"] == "average_of_answers" and row["answered_count"] == 2 and row["evaluated_count"] == 2
    assert row["advice"] == {"proceed": 1, "hold": 1, "reject": 0} and row["interview_date"]


# ---------------------------------------------------------------- filters and pagination
@pytest.fixture
def populated(db_session):
    a, b = make_interview(db_session, "Backend"), make_interview(db_session, "Frontend")
    make_session(db_session, a, "Asha Verma", SessionStatus.EVALUATED, scores=(80,), recs=(Recommendation.PROCEED,))
    make_session(db_session, a, "Ravi Kumar", SessionStatus.EVALUATED, scores=(40,), recs=(Recommendation.REJECT,))
    make_session(db_session, b, "Asha Menon", SessionStatus.PROCESSING)
    make_session(db_session, b, "Zoe Park", SessionStatus.IN_PROGRESS)
    return a, b


def test_search_is_case_insensitive_substring_on_name(api_client, populated):
    assert sorted(names(get(api_client, "/api/dashboard/sessions", search="asha").json())) == ["Asha Menon", "Asha Verma"]
    assert names(get(api_client, "/api/dashboard/sessions", search="  KUMAR ").json()) == ["Ravi Kumar"]


def test_search_wildcards_are_literal_and_email_is_not_searched(api_client, populated):
    assert get(api_client, "/api/dashboard/sessions", search="%").json()["total"] == 0
    assert get(api_client, "/api/dashboard/sessions", search="_").json()["total"] == 0
    assert get(api_client, "/api/dashboard/sessions", search="example.com").json()["total"] == 0


def test_filters_work_alone_and_together(api_client, populated):
    a, b = populated
    assert get(api_client, "/api/dashboard/sessions", interview_id=str(b.id)).json()["total"] == 2
    assert get(api_client, "/api/dashboard/sessions", status="evaluated").json()["total"] == 2
    assert names(get(api_client, "/api/dashboard/sessions", recommendation="reject").json()) == ["Ravi Kumar"]
    both = get(api_client, "/api/dashboard/sessions", search="asha", status="evaluated", interview_id=str(a.id), recommendation="proceed").json()
    assert names(both) == ["Asha Verma"]
    assert get(api_client, "/api/dashboard/sessions", search="asha", status="in_progress").json()["total"] == 0


def test_pagination_total_and_stable_order(api_client, db_session):
    iv = make_interview(db_session)
    for i in range(5):
        make_session(db_session, iv, f"Cand {i}", SessionStatus.IN_PROGRESS)
    first = get(api_client, "/api/dashboard/sessions", page_size=2, page=1).json()
    second = get(api_client, "/api/dashboard/sessions", page_size=2, page=2).json()
    third = get(api_client, "/api/dashboard/sessions", page_size=2, page=3).json()
    assert first["total"] == 5 and [len(p["items"]) for p in (first, second, third)] == [2, 2, 1]
    ids = [r["session_id"] for p in (first, second, third) for r in p["items"]]
    assert len(set(ids)) == 5
    assert get(api_client, "/api/dashboard/sessions", page=9, page_size=2).json()["items"] == []


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"status": "bogus"}, {"recommendation": "maybe"}, {"interview_id": "x"}, {"search": "x" * 101}])
def test_invalid_requests_are_422(api_client, params):
    assert get(api_client, "/api/dashboard/sessions", **params).status_code == 422


def test_missing_or_blank_candidate_name_is_null(api_client, db_session):
    make_session(db_session, make_interview(db_session), "   ", SessionStatus.IN_PROGRESS)
    assert get(api_client, "/api/dashboard/sessions").json()["items"][0]["candidate_name"] is None


# ---------------------------------------------------------------- privacy / isolation
def test_listing_and_detail_never_contain_transcripts_or_email(api_client, db_session):
    session = make_session(db_session, make_interview(db_session), "Asha", scores=(80,), transcript="SECRET-SPOKEN-WORDS")
    for path in ("/api/dashboard/sessions", f"/api/dashboard/sessions/{session.id}", "/api/dashboard/summary"):
        body = api_client.get(path, headers=AUTH).text
        assert "SECRET-SPOKEN-WORDS" not in body and "example.com" not in body and "email" not in body.lower()
        assert "transcript" not in body.lower()


def test_detail_contains_only_the_requested_session(api_client, db_session):
    iv = make_interview(db_session)
    mine = make_session(db_session, iv, "Alice Mine", scores=(80,), transcript="MINE")
    make_session(db_session, iv, "Bob Other", scores=(10,), transcript="OTHER")
    body = api_client.get(f"/api/dashboard/sessions/{mine.id}", headers=AUTH).text
    assert "Alice Mine" in body and "Bob" not in body and "OTHER" not in body


def test_detail_content(api_client, db_session):
    session = make_session(db_session, make_interview(db_session), "Asha", scores=(75.5, 64), recs=(Recommendation.PROCEED, Recommendation.HOLD))
    d = api_client.get(f"/api/dashboard/sessions/{session.id}", headers=AUTH).json()
    assert d["candidate_name"] == "Asha" and d["status"] == "evaluated" and d["overall_score"] == pytest.approx(69.75)
    assert d["score_source"] == "average_of_answers" and d["recommendation"] is None
    assert d["evaluated_count"] == 2 and d["question_count"] == 2 and d["is_complete"] is True
    first = d["answers"][0]
    assert first["overall_score"] == 75.5 and first["recommendation"] == "proceed" and first["strengths"] and first["criteria"]
    assert first["criteria"][0]["explanation"] and first["scale_max"] == 10 and first["nlp"]["status"] == "completed"
    assert "errors" not in first["nlp"] and "models" not in first["nlp"]
    assert len(d["criteria_summary"]["points"]) == 4 and d["criteria_summary"]["scale_max"] == 10


def test_detail_of_unevaluated_session_is_200_with_reasons_not_409(api_client, db_session):
    session = make_session(db_session, make_interview(db_session), "Asha", SessionStatus.SUBMITTED)
    d = api_client.get(f"/api/dashboard/sessions/{session.id}", headers=AUTH).json()
    assert d["overall_score"] is None and d["evaluated_count"] == 0 and d["is_complete"] is False
    assert all(a["status_text"] for a in d["answers"]) and d["criteria_summary"]["points"] == []


def test_dashboard_is_read_only(api_client, db_session):
    from app.models import Evaluation, Report
    session = make_session(db_session, make_interview(db_session), scores=(80,))
    for path in ("/api/dashboard/summary", "/api/dashboard/sessions", f"/api/dashboard/sessions/{session.id}"):
        api_client.get(path, headers=AUTH)
    db_session.expire_all()
    assert db_session.query(Report).count() == 0 and db_session.query(Evaluation).one().overall_score == 80


def test_dashboard_logs_no_candidate_data(api_client, db_session, caplog):
    caplog.set_level("DEBUG")
    session = make_session(db_session, make_interview(db_session), "Zed Secretname", scores=(80,), transcript="SECRET-WORDS")
    for path in ("/api/dashboard/sessions", f"/api/dashboard/sessions/{session.id}"):
        api_client.get(path, headers=AUTH)
    assert "Zed Secretname" not in caplog.text and "SECRET-WORDS" not in caplog.text


def test_listing_uses_a_constant_number_of_queries(api_client, db_session, sqlite_engine):
    import sqlalchemy as sa
    iv = make_interview(db_session)
    seen: list[str] = []

    def count(conn, cursor, statement, *rest):
        seen.append(statement)

    sa.event.listen(sqlite_engine, "before_cursor_execute", count)
    try:
        measured = []
        for n in (2, 8):
            for i in range(n):
                make_session(db_session, iv, f"C{n}-{i}", scores=(50,))
            seen.clear()
            get(api_client, "/api/dashboard/sessions", page_size=100)
            measured.append(len(seen))
    finally:
        sa.event.remove(sqlite_engine, "before_cursor_execute", count)
    assert measured[1] == measured[0]  # more rows, same number of statements: no N+1
