"""Day 8: question bank API + database integration (needs SQLAlchemy, FastAPI; SQLite stand-in DB).

Written to run in CI; NOT executed in the offline build sandbox (see docs/PROGRESS.md)."""

import copy
import uuid

import pytest
import sqlalchemy as sa
import yaml

from app.core.config import DEFAULT_RUBRICS_DIR, get_settings
from app.models import Candidate, Interview, InterviewSession, Question, QuestionType
from app.services.evaluation.pipeline import evaluate_transcript
from app.services.evaluation.providers import MockEvaluationProvider
from app.services.demo_seed import seed_demo_interview
from tests.dashboard_builders import AUTH, TOKEN
from tests.evaluation_samples import TECHNICAL_TRANSCRIPT

BASE = "/api/question-bank"
TEXT = "Explain how database indexes speed up queries."


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("REPORT_ACCESS_TOKEN", TOKEN)
    get_settings.cache_clear()


@pytest.fixture
def rubrics(tmp_path, monkeypatch):
    """A temporary rubric folder with a valid custom rubric, so the shipped files are never touched."""
    data = yaml.safe_load((DEFAULT_RUBRICS_DIR / "default.yaml").read_text(encoding="utf-8"))
    custom = copy.deepcopy(data)
    custom["name"] = "backend-engineer"
    custom["question_types"]["databases"] = copy.deepcopy(data["question_types"]["technical"])
    (tmp_path / "default.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    (tmp_path / "backend-engineer.yaml").write_text(yaml.safe_dump(custom, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("RUBRICS_DIR", str(tmp_path))
    get_settings.cache_clear()
    return tmp_path


def new_interview(client, **overrides):
    body = {"title": "Backend Engineer", "rubric_name": "backend-engineer", **overrides}
    return client.post(f"{BASE}/interviews", json=body, headers=AUTH)


def add_question(client, interview_id, **overrides):
    body = {"text": TEXT, "question_type": "technical", **overrides}
    return client.post(f"{BASE}/interviews/{interview_id}/questions", json=body, headers=AUTH)


@pytest.fixture
def interview(api_client, rubrics):
    return new_interview(api_client).json()["id"]


# ---------------------------------------------------------------- authorisation
ROUTES = [
    ("get", f"{BASE}/rubrics", None), ("get", f"{BASE}/questions", None), ("get", f"{BASE}/questions/{uuid.uuid4()}", None),
    ("post", f"{BASE}/interviews", {"title": "T", "rubric_name": "default"}),
    ("put", f"{BASE}/interviews/{uuid.uuid4()}/active", {"active": True}),
    ("post", f"{BASE}/interviews/{uuid.uuid4()}/questions", {"text": TEXT, "question_type": "technical"}),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_route_needs_the_token(api_client, rubrics, method, path, body):
    assert api_client.request(method.upper(), path, json=body).status_code == 401
    wrong = {"Authorization": "Bearer wrong-wrong-wrong-wrong"}
    assert api_client.request(method.upper(), path, json=body, headers=wrong).status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_routes_are_disabled_without_a_configured_token(api_client, monkeypatch, method, path, body):
    monkeypatch.delenv("REPORT_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    assert api_client.request(method.upper(), path, json=body, headers=AUTH).status_code == 503


def test_a_rejected_request_writes_nothing(api_client, db_session, rubrics):
    api_client.post(f"{BASE}/interviews", json={"title": "T", "rubric_name": "backend-engineer"})
    assert db_session.scalar(sa.select(sa.func.count(Interview.id))) == 0


# ---------------------------------------------------------------- rubric catalogue
def test_rubric_list_shows_keys_and_weights_but_no_prompt_material(api_client, rubrics):
    (rubrics / "broken.yaml").write_text("name: broken\n", encoding="utf-8")
    body = api_client.get(f"{BASE}/rubrics", headers=AUTH)
    assert body.status_code == 200
    by_name = {r["name"]: r for r in body.json()}
    assert set(by_name) == {"backend-engineer", "broken", "default"}
    assert by_name["backend-engineer"]["valid"] and set(by_name["backend-engineer"]["rubric_keys"]) == {"behavioral", "databases", "technical"}
    assert by_name["default"]["score_scale"] == {"min": 0, "max": 10}
    assert by_name["broken"]["valid"] is False and by_name["broken"]["problem"] and by_name["broken"]["rubric_keys"] == {}
    assert "strong_examples" not in body.text and "Correctly distinguishes" not in body.text


# ---------------------------------------------------------------- creating interviews
def test_interview_is_created_inactive_and_hidden_from_candidates(api_client, rubrics):
    response = new_interview(api_client, description="Role", total_time_limit_seconds=900)
    assert response.status_code == 201
    created = response.json()
    assert created["is_active"] is False and created["question_count"] == 0 and created["rubric_name"] == "backend-engineer"
    assert created["id"] not in [i["id"] for i in api_client.get("/api/interviews").json()]


def test_interview_needs_an_existing_valid_rubric(api_client, rubrics):
    assert new_interview(api_client, rubric_name="nope").status_code == 422
    (rubrics / "bad.yaml").write_text("name: bad\n", encoding="utf-8")
    broken = new_interview(api_client, rubric_name="bad")
    assert broken.status_code == 409 and "validate_rubrics" in broken.json()["detail"]
    assert "name: bad" not in broken.text


@pytest.mark.parametrize("body", [{"title": ""}, {"rubric_name": "../x"}, {"interview_type": "x"}, {"is_active": True}, {"total_time_limit_seconds": 5}])
def test_invalid_interview_bodies_are_422(api_client, rubrics, body):
    assert new_interview(api_client, **body).status_code == 422


# ---------------------------------------------------------------- creating and retrieving questions
def test_question_is_stored_with_normalised_metadata_and_can_be_retrieved(api_client, interview):
    created = add_question(api_client, interview, rubric_key="databases", category="Databases", difficulty="medium",
                           expected_skills=["SQL", "Indexing", "sql"], time_limit_seconds=120)
    assert created.status_code == 201
    item = created.json()
    assert (item["position"], item["rubric_key"], item["category"], item["difficulty"]) == (1, "databases", "databases", "medium")
    assert item["expected_skills"] == ["sql", "indexing"] and item["time_limit_seconds"] == 120 and item["interview_title"] == "Backend Engineer"
    again = api_client.get(f"{BASE}/questions/{item['id']}", headers=AUTH)
    assert again.status_code == 200 and again.json() == item


def test_rubric_key_defaults_to_the_question_type_and_positions_count_up(api_client, interview):
    first = add_question(api_client, interview, text="Explain processes versus threads.").json()
    second = add_question(api_client, interview, text="Tell us about a recent project.", question_type="behavioral").json()
    assert (first["rubric_key"], first["position"], second["rubric_key"], second["position"]) == ("technical", 1, "behavioral", 2)
    assert first["category"] is None and first["difficulty"] is None and first["expected_skills"] == []


def test_explicit_position_must_be_free(api_client, interview):
    assert add_question(api_client, interview, position=5).json()["position"] == 5
    clash = add_question(api_client, interview, text="Another question about indexes.", position=5)
    assert clash.status_code == 409 and "Position 5" in clash.json()["detail"]
    assert add_question(api_client, interview, text="A third question about caching.").json()["position"] == 6


def test_unknown_interview_and_unknown_question_are_404(api_client, rubrics):
    assert add_question(api_client, uuid.uuid4()).status_code == 404
    assert api_client.get(f"{BASE}/questions/{uuid.uuid4()}", headers=AUTH).status_code == 404
    assert api_client.get(f"{BASE}/questions/not-a-uuid", headers=AUTH).status_code == 422
    assert api_client.put(f"{BASE}/interviews/{uuid.uuid4()}/active", json={"active": True}, headers=AUTH).status_code == 404


def test_question_must_use_a_rubric_key_that_exists(api_client, interview):
    bad = add_question(api_client, interview, rubric_key="networking")
    assert bad.status_code == 422 and "Available: behavioral, databases, technical" in bad.json()["detail"]


def test_interview_type_restricts_question_types(api_client, rubrics):
    technical = new_interview(api_client, interview_type="technical").json()["id"]
    refused = add_question(api_client, technical, question_type="behavioral")
    assert refused.status_code == 422 and "technical questions only" in refused.json()["detail"]
    assert add_question(api_client, technical).status_code == 201


def test_duplicate_text_is_refused_case_insensitively(api_client, interview):
    assert add_question(api_client, interview).status_code == 201
    assert add_question(api_client, interview, text=TEXT.upper()).status_code == 409


def test_interview_question_limit(api_client, interview):
    for i in range(50):
        assert add_question(api_client, interview, text=f"Question number {i:02d} about systems.").status_code == 201
    assert add_question(api_client, interview, text="One question too many here.").status_code == 409


def test_no_questions_can_be_added_once_candidates_have_started(api_client, db_session, interview):
    add_question(api_client, interview)
    api_client.put(f"{BASE}/interviews/{interview}/active", json={"active": True}, headers=AUTH)
    started = api_client.post("/api/sessions", json={"interview_id": interview, "candidate_name": "A B", "candidate_email": "a@example.com", "consent": True})
    assert started.status_code in (200, 201)
    late = add_question(api_client, interview, text="A late question about queues.")
    assert late.status_code == 409 and "already has sessions" in late.json()["detail"]


@pytest.mark.parametrize("body", [{"text": "short"}, {"question_type": "mixed"}, {"difficulty": "x"}, {"expected_skills": "sql"}, {"is_active": True}])
def test_invalid_question_bodies_are_422_and_store_nothing(api_client, db_session, interview, body):
    assert add_question(api_client, interview, **body).status_code == 422
    assert db_session.scalar(sa.select(sa.func.count(Question.id))) == 0


# ---------------------------------------------------------------- activation and the candidate workflow
def test_activation_needs_questions_then_the_candidate_workflow_runs_unchanged(api_client, interview):
    url = f"{BASE}/interviews/{interview}/active"
    assert api_client.put(url, json={"active": True}, headers=AUTH).status_code == 409
    add_question(api_client, interview, category="databases", expected_skills=["sql"], difficulty="easy")
    assert api_client.put(url, json={"active": True}, headers=AUTH).json()["is_active"] is True
    assert interview in [i["id"] for i in api_client.get("/api/interviews").json()]
    started = api_client.post("/api/sessions", json={"interview_id": interview, "candidate_name": "Asha Verma", "candidate_email": "asha@example.com", "consent": True})
    assert started.status_code in (200, 201)
    view = started.json()
    assert [question["text"] for question in view["questions"]] == [TEXT]
    leaked = {"category", "difficulty", "expected_skills", "rubric_key"} & set(view["questions"][0])
    assert not leaked, f"candidate API leaks question metadata: {leaked}"
    assert api_client.put(url, json={"active": False}, headers=AUTH).json()["is_active"] is False
    assert interview not in [i["id"] for i in api_client.get("/api/interviews").json()]


def test_activation_refuses_a_question_the_rubric_can_no_longer_score(api_client, interview, rubrics):
    add_question(api_client, interview, rubric_key="databases")
    data = yaml.safe_load((rubrics / "backend-engineer.yaml").read_text(encoding="utf-8"))
    del data["question_types"]["databases"]
    (rubrics / "backend-engineer.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    refused = api_client.put(f"{BASE}/interviews/{interview}/active", json={"active": True}, headers=AUTH)
    assert refused.status_code == 409 and "cannot be evaluated" in refused.json()["detail"]


def test_a_stored_question_is_scored_by_the_unchanged_day4_pipeline(api_client, db_session, interview, rubrics):
    created = add_question(api_client, interview, rubric_key="databases", category="databases").json()
    question = db_session.get(Question, uuid.UUID(created["id"]))
    result = evaluate_transcript(
        provider=MockEvaluationProvider(), rubrics_dir=rubrics, rubric_name=question.interview.rubric_name, question_text=question.text,
        question_type=question.question_type, rubric_key=question.rubric_key, transcript=TECHNICAL_TRANSCRIPT,
    )
    assert result.fields["rubric_name"] == "backend-engineer" and 0 <= result.fields["overall_score"] <= 100


# ---------------------------------------------------------------- listing and filters
@pytest.fixture
def bank(api_client, rubrics):
    a = new_interview(api_client, title="Backend").json()["id"]
    b = new_interview(api_client, title="Platform", rubric_name="default").json()["id"]
    add_question(api_client, a, text="Explain SQL indexes in detail.", rubric_key="databases", category="databases", difficulty="medium", expected_skills=["sql", "indexing"])
    add_question(api_client, a, text="Describe how NoSQL stores scale out.", rubric_key="databases", category="databases", difficulty="hard", expected_skills=["nosql"])
    add_question(api_client, a, text="Tell us about a production incident.", question_type="behavioral", category="teamwork", difficulty="easy")
    add_question(api_client, b, text="Explain processes and threads clearly.", category="systems", difficulty="easy", expected_skills=["operating systems"])
    return a, b


def texts(response):
    assert response.status_code == 200, response.text
    return sorted(item["text"] for item in response.json()["items"])


def listing(client, **params):
    return client.get(f"{BASE}/questions", params=params, headers=AUTH)


def test_listing_without_filters_returns_everything_in_a_stable_order(api_client, bank):
    body = listing(api_client).json()
    assert body["total"] == 4 and [i["interview_title"] for i in body["items"]] == ["Backend"] * 3 + ["Platform"]
    assert [i["position"] for i in body["items"][:3]] == [1, 2, 3]


def test_each_filter_works_alone(api_client, bank):
    a, b = bank
    assert len(texts(listing(api_client, interview_id=b))) == 1
    assert len(texts(listing(api_client, question_type="behavioral"))) == 1
    assert len(texts(listing(api_client, category="databases"))) == 2
    assert len(texts(listing(api_client, difficulty="easy"))) == 2
    assert texts(listing(api_client, search="INCIDENT")) == ["Tell us about a production incident."]


def test_skill_filter_matches_whole_entries_only(api_client, bank):
    assert texts(listing(api_client, skill="sql")) == ["Explain SQL indexes in detail."]  # not the "nosql" question
    assert texts(listing(api_client, skill="NoSQL")) == ["Describe how NoSQL stores scale out."]
    assert texts(listing(api_client, skill="operating systems")) == ["Explain processes and threads clearly."]
    assert listing(api_client, skill="index").json()["total"] == 0


def test_filters_combine_with_and(api_client, bank):
    a, _ = bank
    assert texts(listing(api_client, interview_id=a, category="databases", difficulty="hard")) == ["Describe how NoSQL stores scale out."]
    assert listing(api_client, interview_id=a, category="systems").json()["total"] == 0
    assert listing(api_client, category="databases", skill="sql", difficulty="medium", question_type="technical", search="indexes").json()["total"] == 1


def test_search_and_filter_wildcards_are_literal(api_client, bank):
    for params in ({"search": "%"}, {"search": "_"}, {"skill": "s%l"}, {"category": "data_ases"}):
        assert listing(api_client, **params).json()["total"] == 0


def test_pagination(api_client, bank):
    pages = [listing(api_client, page=p, page_size=3).json() for p in (1, 2, 3)]
    assert [len(p["items"]) for p in pages] == [3, 1, 0] and all(p["total"] == 4 for p in pages)
    assert len({i["id"] for p in pages for i in p["items"]}) == 4


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"question_type": "mixed"}, {"difficulty": "x"},
                                    {"interview_id": "x"}, {"category": "Bad Cat!"}, {"skill": "semi;colon"}, {"search": "x" * 101}])
def test_invalid_filters_are_422(api_client, bank, params):
    assert listing(api_client, **params).status_code == 422


def test_existing_questions_without_metadata_are_listed_with_empty_values(api_client, session_factory, rubrics):
    with session_factory() as db:
        seed_demo_interview(db)
    items = listing(api_client).json()["items"]
    assert len(items) == 4 and all(i["category"] is None and i["difficulty"] is None and i["expected_skills"] == [] for i in items)
    assert listing(api_client, difficulty="easy").json()["total"] == 0


# ---------------------------------------------------------------- privacy and side effects
def test_responses_carry_no_candidate_data(api_client, db_session, bank):
    db_session.add(Candidate(full_name="Zed Secretname", email="zed@example.com"))
    db_session.commit()
    body = listing(api_client).text + api_client.get(f"{BASE}/rubrics", headers=AUTH).text
    assert "Zed" not in body and "example.com" not in body


def test_reading_never_writes(api_client, db_session, bank):
    before = db_session.scalar(sa.select(sa.func.count(Question.id)))
    for path in (f"{BASE}/rubrics", f"{BASE}/questions"):
        api_client.get(path, headers=AUTH)
    db_session.expire_all()
    assert db_session.scalar(sa.select(sa.func.count(Question.id))) == before


def test_question_text_is_not_logged(api_client, interview, caplog):
    caplog.set_level("DEBUG")
    add_question(api_client, interview, text="Confidential question wording about SECRET-PROJECT.")
    assert "SECRET-PROJECT" not in caplog.text
