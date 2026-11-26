"""Sample interview used for development and demos. It is clearly labelled as sample data."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Interview, InterviewType, Question, QuestionType

DEMO_TITLE = "HireIQ Demo Interview (sample questions)"

DEMO_QUESTIONS: list[tuple[QuestionType, str, int]] = [
    (QuestionType.TECHNICAL, "Explain the difference between a process and a thread, and when you would use each.", 120),
    (QuestionType.TECHNICAL, "How would you design a REST API endpoint for uploading a large file reliably?", 120),
    (QuestionType.BEHAVIORAL, "Tell us about a time you had to learn a new technology quickly. What was the outcome?", 120),
    (QuestionType.BEHAVIORAL, "Describe a disagreement with a teammate and how you resolved it.", 120),
]


def seed_demo_interview(db: Session) -> tuple[Interview, bool]:
    """Create the demo interview if missing. Returns (interview, created)."""
    existing = db.scalar(sa.select(Interview).where(Interview.title == DEMO_TITLE))
    if existing is not None:
        return existing, False
    interview = Interview(
        title=DEMO_TITLE,
        description="Sample data for development. Not a real interview.",
        interview_type=InterviewType.MIXED,
        rubric_name="default",  # rubric YAML arrives on Day 4
        total_time_limit_seconds=900,
    )
    interview.questions = [
        Question(position=i, text=text, question_type=qtype, rubric_key=qtype.value, time_limit_seconds=limit)
        for i, (qtype, text, limit) in enumerate(DEMO_QUESTIONS, start=1)
    ]
    db.add(interview)
    db.commit()
    return interview, True
