"""VADER sentiment of ONE answer (Day 5). Deterministic: VADER is a fixed lexicon + rules, no randomness.

Labels use VADER's own recommended compound thresholds: >= 0.05 positive, <= -0.05 negative, else neutral.
Limitations: VADER was built for short social-media English; it reads the TONE of the wording, not correctness.
Technical answers are mostly neutral, a calm answer is not a weak one, and negation/irony/domain words
("exception", "failed", "crash") can shift the score for reasons unrelated to the candidate. The result is context
only and is never used in scoring.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.services.nlp.spacy_backend import NlpUnavailableError

POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05


def label_for(compound: float) -> str:
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


@lru_cache(maxsize=1)
def _analyzer() -> Any:
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        raise NlpUnavailableError("vader_not_installed", "vaderSentiment is not installed.") from None
    return SentimentIntensityAnalyzer()


def analyze_sentiment(text: str, analyzer: Any = None) -> dict:
    """-> {"positive", "negative", "neutral", "compound", "label"} with scores rounded to 4 decimals."""
    scores = (analyzer or _analyzer()).polarity_scores(text)
    compound = round(float(scores["compound"]), 4)
    return {
        "positive": round(float(scores["pos"]), 4),
        "negative": round(float(scores["neg"]), 4),
        "neutral": round(float(scores["neu"]), 4),
        "compound": compound,
        "label": label_for(compound),
    }
