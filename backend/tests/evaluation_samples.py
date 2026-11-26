"""Realistic sample data for the Day 4 Phase 2 tests (not a test module: no test functions here).

Questions are the demo-seed questions; transcripts are written the way Whisper typically returns speech
(punctuation, filler words, no corrections). No real person, API key or external service is involved.
"""

from pathlib import Path
from typing import Any

from app.schemas.evaluation import EvaluationContext
from app.services.rubrics import Rubric, load_rubric

RUBRICS_DIR = Path(__file__).resolve().parents[1] / "config" / "rubrics"

TECHNICAL_QUESTION = "Explain the difference between a process and a thread, and when you would use each."
TECHNICAL_TRANSCRIPT = (
    "So, a process is an independent program in execution with its own address space, while threads live "
    "inside a process and share its memory. Because threads share memory they are cheap to create and "
    "communicate quickly, but you need locks to avoid race conditions. I would use threads for I/O bound work "
    "like handling many network requests, and separate processes when I need isolation, for example running "
    "untrusted code, because a crash in one process does not take down the others. In Python, because of the "
    "global interpreter lock, I would pick processes for CPU bound work."
)

BEHAVIORAL_QUESTION = "Tell us about a time you had to learn a new technology quickly. What was the outcome?"
BEHAVIORAL_TRANSCRIPT = (
    "Last year my team needed to move our reporting jobs to Kubernetes and nobody had used it. I volunteered "
    "to own the migration. I spent two weekends going through the official tutorials, built a small test "
    "cluster, and wrote a runbook for the team. We migrated the first job in three weeks and the failed-run "
    "rate dropped from about eight percent to under one percent. Looking back, I would have asked for a "
    "review from our platform team earlier, because I lost a few days on a networking mistake."
)

# Verbatim, contiguous pieces of the transcripts above.
TECHNICAL_QUOTES = (
    "threads live inside a process and share its memory",
    "you need locks to avoid race conditions",
    "separate processes when I need isolation",
    "a crash in one process does not take down the others",
)
BEHAVIORAL_QUOTES = (
    "I volunteered to own the migration",
    "built a small test cluster, and wrote a runbook for the team",
    "the failed-run rate dropped from about eight percent to under one percent",
    "I would have asked for a review from our platform team earlier",
)


def default_rubric() -> Rubric:
    return load_rubric("default", RUBRICS_DIR)


def context_for(rubric_key: str, transcript: str, rubric: Rubric | None = None) -> EvaluationContext:
    rubric = rubric or default_rubric()
    return EvaluationContext.from_question_rubric(rubric.for_key(rubric_key), rubric.score_scale, transcript)


def valid_response(rubric_key: str = "technical", quotes: tuple[str, ...] = TECHNICAL_QUOTES, score: int = 7) -> dict[str, Any]:
    """A response that passes every check for the default rubric (as a plain dict, like json.loads output)."""
    keys = [c.key for c in default_rubric().for_key(rubric_key).criteria]
    return {
        "overall_score": 7.5,
        "criteria_scores": [
            {
                "criterion_key": key,
                "score": score,
                "explanation": f"The answer addresses {key.replace('_', ' ')} reasonably well but not exhaustively.",
                "evidence_quotes": [quotes[i % len(quotes)]],
            }
            for i, key in enumerate(keys)
        ],
        "strengths": ["Clear distinction between the two concepts", "Gives a concrete use case"],
        "areas_for_improvement": ["Could discuss context-switch costs"],
        "summary": "A correct and well organised answer with a few missed trade-offs.",
        "recommendation": "proceed",
    }
