"""Builds report inputs for the Day 6 tests (pure data; no database, no model)."""

from datetime import datetime, timezone

from app.services.reporting.data import ReportData, build_report

TK = ["technical_accuracy", "depth_of_understanding", "problem_solving_approach", "communication_clarity"]
BK = ["situation_and_structure", "ownership_and_actions", "results_and_impact", "reflection_and_learning"]
SESSION_ID = "3f2b8c1e-aaaa-bbbb-cccc-111122223333"
NOW = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)

NLP = {
    "schema_version": 1, "status": "completed", "word_count": 95,
    "keywords": [{"text": "race condition", "count": 1}], "entities": [{"text": "Python", "label": "TECHNOLOGY", "count": 1}],
    "sentiment": {"positive": 0.1, "negative": 0.02, "neutral": 0.88, "compound": 0.4, "label": "positive", "note": "x"},
    "confidence": {"kind": "heuristic", "score": 0.71, "label": "high", "affects_evaluation": False, "disclaimer": "d", "unavailable": [],
                   "indicators": [{"name": "completeness", "value": 1.0, "weight": 1.0, "limitation": "A short answer can be complete."}]},
    "errors": {}, "models": {},
}


def evaluation(keys=TK, scores=(8, 7, 6, 9), overall=75.5, rec="proceed", scale=(0, 10), nlp=NLP, quote="threads share memory"):
    return {
        "overall_score": overall, "recommendation": rec, "explanation": "A correct answer with a few missed trade-offs.",
        "criteria_scores": {
            k: {"score": s, "weight": 0.25, "weighted_contribution": s * 0.25, "explanation": f"Explanation for {k}.", "evidence_quotes": [quote]}
            for k, s in zip(keys, scores)
        },
        "evaluation_details": {"strengths": ["Clear distinction"], "areas_for_improvement": ["Discuss context switches"],
                               "score_scale": {"min": scale[0], "max": scale[1]}},
        "nlp_enrichment": nlp,
    }


def answer(position=1, transcript="Threads share memory.", ev=None, **kw):
    raw = {"position": position, "question": f"Question text {position}?", "transcript": transcript,
           "transcription_status": "completed", "evaluation_status": "completed" if ev else "pending"}
    if ev is not None:
        raw["evaluation"] = ev
    raw.update(kw)
    return raw


def report(answers=None, **kw) -> ReportData:
    if answers is None:
        answers = [answer(1, ev=evaluation()), answer(2, ev=evaluation(BK, (6, 7, 8, 5), 64, "hold"))]
    args = dict(session_id=SESSION_ID, session_status="completed", candidate_id="c1c1c1c1-0000-1111-2222-333344445555",
                candidate_name="Asha Verma", interview_title="Backend Engineer Screening",
                interview_date=datetime(2026, 11, 20, 9, 30), answers=answers)
    args.update(kw)
    return build_report(**args)
