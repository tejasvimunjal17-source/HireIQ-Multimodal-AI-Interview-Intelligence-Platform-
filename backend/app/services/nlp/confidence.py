"""Rule-based CONFIDENCE SIGNAL (Day 5). An experimental heuristic, NOT a measure of a person.

It looks only at the TEXT of one answer and its question, with five documented signals, each 0..1:

  signal              what it looks at                                  documented limitation
  completeness  .25   words in the answer, saturating at 40 words       a short answer can be fully correct; this
                                                                        under-rates concise speakers
  structure     .20   sentences (up to 3) and linking words              depends on the transcriber's punctuation;
                      ("first", "because", "for example", ...)           not every good answer is structured this way
  supporting_detail .25  distinct keywords + entities + numbers (cap 8) rewards specificity, cannot judge accuracy
  directness    .20   question words repeated in the first 40 words      paraphrasing or abstract answers score lower
  low_hedging   .10   explicit uncertainty phrases ("I don't know",     uncertainty can be honest and appropriate;
                      "not sure", "maybe", ...) above 3 per 100 words     phrases are English-only and cultural
                                                                        styles of hedging differ

Deliberately NOT used: sentiment, grammar, spelling, accent, pronunciation, filler words ("um", "like"), speech
speed, pauses, answer duration, vocabulary level, names, or anything about the person. The weights sum to 1; a
missing signal is left out and the rest are re-weighted. The result never feeds the score or the recommendation
(`affects_evaluation` is always False) and must not be used to rank or reject people.
"""

from __future__ import annotations

import math
import re

WEIGHTS = {"completeness": 0.25, "structure": 0.20, "supporting_detail": 0.25, "directness": 0.20, "low_hedging": 0.10}
assert math.isclose(sum(WEIGHTS.values()), 1.0)  # a typo here must fail at import, not silently skew results

COMPLETE_WORDS = 40
STRUCTURE_SENTENCES = 3
STRUCTURE_MARKERS = 2
DETAIL_TARGET = 8
DIRECT_WINDOW_WORDS = 40
DIRECT_MIN_OVERLAP = 3
HEDGE_ALLOWANCE_PER_100 = 3.0
HEDGE_ZERO_AT_PER_100 = 10.0
LOW_BELOW, HIGH_FROM = 0.40, 0.70

LIMITATIONS = {
    "completeness": "A short answer can be complete and correct; concise speakers are under-rated.",
    "structure": "Depends on the transcriber's punctuation; good answers can be organised differently.",
    "supporting_detail": "Rewards specific wording only; it cannot judge whether the details are correct.",
    "directness": "Lexical overlap with the question; paraphrased or abstract answers score lower.",
    "low_hedging": "Uncertainty can be honest and appropriate; the phrase list is English-only and style-dependent.",
}

_WORD = re.compile(r"[a-z0-9][a-z0-9'+#./-]*")
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_SENTENCE_END = re.compile(r"[.!?]+")
STRUCTURE_MARKER_PHRASES = (
    "first", "second", "third", "finally", "because", "for example", "for instance", "therefore", "so that",
    "however", "as a result", "in addition", "overall", "for this reason",
)
HEDGE_PHRASES = (
    "i don't know", "i do not know", "i'm not sure", "i am not sure", "not sure", "i'm not certain", "i guess",
    "maybe", "perhaps", "probably", "kind of", "sort of", "no idea",
)
_STOP = frozenset(
    "a an the and or but if then than that this these those of to in on at by for with from as is are was were be been "
    "being do does did have has had i you he she it we they me my our your their what which who whom how why when where "
    "about into over under can could would should will shall may might must not no so such there here also just very "
    "tell explain describe give us time".split()
)


def _norm(text: str) -> str:
    return text.lower().replace("’", "'").replace("‘", "'")


def _content_words(text: str) -> set[str]:
    words = (w.strip("'./-") for w in _WORD.findall(_norm(text)))
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words if len(w) >= 3 and w not in _STOP}


def _phrase_count(text: str, phrases: tuple[str, ...]) -> int:
    return sum(len(re.findall(r"(?<![a-z'])" + re.escape(p) + r"(?![a-z'])", text)) for p in phrases)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def confidence_signal(
    transcript: str, question: str = "", *, keyword_count: int | None = None, entity_count: int | None = None
) -> dict | None:
    """-> dict shaped like schemas.nlp.Confidence, or None when there is nothing to assess (empty transcript)."""
    text = _norm(transcript or "")
    words = _WORD.findall(text)
    if not words:
        return None
    n = len(words)

    signals: dict[str, float] = {"completeness": _clamp01(n / COMPLETE_WORDS)}

    sentences = sum(1 for part in _SENTENCE_END.split(text) if part.strip())
    markers = _phrase_count(text, STRUCTURE_MARKER_PHRASES)
    signals["structure"] = 0.5 * _clamp01(sentences / STRUCTURE_SENTENCES) + 0.5 * _clamp01(markers / STRUCTURE_MARKERS)

    known = [c for c in (keyword_count, entity_count) if c is not None]
    if known:
        units = sum(known) + len(_NUMBER.findall(text))
        signals["supporting_detail"] = _clamp01(units / DETAIL_TARGET)

    question_words = _content_words(question or "")
    if question_words:
        early = _content_words(" ".join(words[:DIRECT_WINDOW_WORDS]))
        signals["directness"] = _clamp01(len(question_words & early) / min(DIRECT_MIN_OVERLAP, len(question_words)))

    rate = _phrase_count(text, HEDGE_PHRASES) / n * 100
    signals["low_hedging"] = 1.0 - _clamp01(
        (rate - HEDGE_ALLOWANCE_PER_100) / (HEDGE_ZERO_AT_PER_100 - HEDGE_ALLOWANCE_PER_100)
    )

    total_weight = math.fsum(WEIGHTS[name] for name in signals)
    score = math.fsum(WEIGHTS[name] * value for name, value in signals.items()) / total_weight
    label = "low" if score < LOW_BELOW else "moderate" if score < HIGH_FROM else "high"
    return {
        "kind": "heuristic",
        "score": round(score, 4),
        "label": label,
        "indicators": [
            {"name": name, "value": round(value, 4), "weight": round(WEIGHTS[name] / total_weight, 4),
             "limitation": LIMITATIONS[name]}
            for name, value in signals.items()
        ],
        "unavailable": [name for name in WEIGHTS if name not in signals],
        "affects_evaluation": False,
    }
