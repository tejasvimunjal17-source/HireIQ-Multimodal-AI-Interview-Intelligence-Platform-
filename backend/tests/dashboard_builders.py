"""Rows for the Day 7 dashboard tests (needs SQLAlchemy; used only by DB/API tests)."""

import uuid
from datetime import datetime, timezone

from app.models import (
    Candidate, CandidateResponse, Evaluation, EvaluationStatus, Interview, InterviewSession, Question, QuestionType, Recommendation,
    Report, SessionStatus, TranscriptionStatus,
)
from tests.report_samples import evaluation

TOKEN = "unit-test-dashboard-token-012345"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_interview(db, title="Backend Screening", questions=2) -> Interview:
    interview = Interview(title=title, rubric_name="default", questions=[
        Question(position=i + 1, text=f"{title} question {i + 1}?", question_type=QuestionType.TECHNICAL) for i in range(questions)
    ])
    db.add(interview)
    db.commit()
    return interview


def make_session(db, interview, name="Asha Verma", status=SessionStatus.EVALUATED, scores=(), recs=(), transcript="Private spoken words.",
                 report=None, nlp=True) -> InterviewSession:
    """`scores`: stored overall_score per evaluated answer (one answer per score, in question order)."""
    candidate = Candidate(full_name=name, email=f"{uuid.uuid4().hex[:10]}@example.com")
    session = InterviewSession(candidate=candidate, interview=interview, status=status,
                               started_at=datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    db.add_all([candidate, session])
    for index, score in enumerate(scores):
        response = CandidateResponse(
            session=session, question=interview.questions[index], transcription_status=TranscriptionStatus.COMPLETED,
            transcript=transcript, evaluation_status=EvaluationStatus.COMPLETED,
        )
        rec = recs[index] if index < len(recs) else Recommendation.HOLD
        ev = evaluation(overall=score, rec=rec.value, nlp=None if not nlp else evaluation()["nlp_enrichment"])
        db.add(response)
        db.add(Evaluation(
            response=response, overall_score=score, criteria_scores=ev["criteria_scores"], explanation=ev["explanation"],
            nlp_enrichment=ev["nlp_enrichment"], llm_provider="mock", llm_model="m", rubric_name="default", recommendation=rec,
            evaluation_details=ev["evaluation_details"],
        ))
    if report is not None:
        db.add(Report(session=session, overall_score=report[0], recommendation=report[1]))
    db.commit()
    return session
