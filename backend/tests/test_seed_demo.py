from app.models import QuestionType
from app.services.demo_seed import DEMO_TITLE, seed_demo_interview


def test_seed_creates_labelled_sample_interview_once(db_session):
    first, created = seed_demo_interview(db_session)
    assert created is True
    assert "sample" in first.title.lower() and first.title == DEMO_TITLE
    assert [q.position for q in first.questions] == [1, 2, 3, 4]
    assert {q.question_type for q in first.questions} == {QuestionType.TECHNICAL, QuestionType.BEHAVIORAL}

    second, created_again = seed_demo_interview(db_session)
    assert created_again is False and second.id == first.id
