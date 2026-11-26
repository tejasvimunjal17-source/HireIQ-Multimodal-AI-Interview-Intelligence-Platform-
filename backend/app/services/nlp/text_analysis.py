"""Keyword and entity SELECTION (Day 5). Pure Python: no spaCy import, no model, easy to test.

spacy_backend.py converts a spaCy document into the small records below; this module decides what to keep.

Keywords are noun phrases and proper/common nouns that carry content. They are ranked by
    (1 + 0.3 * ln(count)) * (1 + 0.5 * (words - 1)) * (1.5 if the phrase has a proper noun else 1)
so frequency counts for little and a specific multi-word phrase ("failed-run rate") or a name ("Kubernetes") outranks a vague noun that merely
repeats. Vague nouns ("thing", "way", "lot", ...) are dropped, as are phrases made only of stop words.
Limitation: this is lexical, so it cannot tell whether a keyword was used correctly.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

MAX_KEYWORDS = 10
MAX_ENTITIES = 20
MAX_TEXT_LENGTH = 80
MIN_KEYWORD_CHARS = 3

# Vague nouns that say nothing about the content of an answer.
GENERIC_WORDS = frozenset({
    "thing", "things", "stuff", "lot", "lots", "way", "ways", "kind", "kinds", "sort", "bit", "part", "time", "times",
    "day", "days", "year", "years", "week", "weeks", "something", "anything", "everything", "nothing", "someone",
    "anyone", "everyone", "one", "ones", "case", "point", "example", "idea", "question", "answer", "fact", "reason",
    "person", "people", "guy", "work", "job", "place", "end", "side", "number", "etc",
})

# Entities worth keeping. NORP (nationality / religious / political groups) is excluded on purpose, and so are
# purely numeric labels (CARDINAL, ORDINAL, QUANTITY, PERCENT, MONEY, TIME), which are noise here.
ALLOWED_LABELS = frozenset({
    "ORG", "PERSON", "GPE", "LOC", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE", "DATE", "TECHNOLOGY",
})
# When the same text gets two labels, the more specific one wins (a gazetteer match beats a statistical guess).
LABEL_PRIORITY = {"TECHNOLOGY": 0, "PRODUCT": 1, "ORG": 2, "PERSON": 3, "GPE": 4, "LOC": 5, "FAC": 6}

# Small built-in gazetteer: technologies the statistical model often mislabels or misses. Matching is
# case-insensitive and exact (whole words). Extend it here; nothing else needs to change.
TECHNOLOGY_TERMS = (
    "python", "java", "javascript", "typescript", "golang", "kotlin", "c++", "c#", "sql", "nosql",
    "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "kafka", "rabbitmq", "celery", "elasticsearch",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "git", "github", "gitlab", "linux", "nginx",
    "aws", "azure", "gcp", "vue", "node.js", "django", "flask", "fastapi",
    "tensorflow", "pytorch", "pandas", "numpy", "hadoop", "graphql", "grpc", "api", "oauth",
    "ci/cd", "prometheus", "grafana", "snowflake", "airflow",
)

_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Tok:
    """The few spaCy token attributes the selection needs."""

    text: str
    lemma: str
    pos: str  # coarse part of speech: NOUN, PROPN, ADJ, DET, ...
    is_stop: bool = False
    is_alpha: bool = True


_TRIM_POS = {"DET", "PRON", "PUNCT", "ADP", "CCONJ", "SCONJ", "PART", "AUX", "NUM", "SYM", "X", "INTJ", "ADV"}


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text).strip(" \t\n.,;:!?\"'()[]")


def _trim(tokens: tuple[Tok, ...]) -> tuple[Tok, ...]:
    """Remove leading/trailing determiners, pronouns, stop words and punctuation ("the", "my", "a few")."""
    start, end = 0, len(tokens)
    while start < end and (tokens[start].pos in _TRIM_POS or tokens[start].is_stop):
        start += 1
    while end > start and (tokens[end - 1].pos in _TRIM_POS or tokens[end - 1].is_stop):
        end -= 1
    return tokens[start:end]


def _candidate(tokens: tuple[Tok, ...]) -> tuple[str, str, int, bool] | None:
    """-> (key, surface, word_count, has_proper_noun) or None when the phrase carries no content."""
    kept = _trim(tuple(tokens))
    if not kept or not any(t.pos in ("NOUN", "PROPN") for t in kept):
        return None
    lemmas = [t.lemma.lower() for t in kept]
    if all(w in GENERIC_WORDS for w in lemmas):
        return None
    if len(kept) == 1 and (len(kept[0].text) < MIN_KEYWORD_CHARS or not kept[0].is_alpha):
        return None
    surface = _clean(" ".join(t.text for t in kept)).lower()
    if not surface or len(surface) > MAX_TEXT_LENGTH:
        return None
    return " ".join(lemmas), surface, len(kept), any(t.pos == "PROPN" for t in kept)


def select_keywords(phrases: list[tuple[Tok, ...]], limit: int = MAX_KEYWORDS) -> list[dict]:
    """`phrases`: noun chunks AND single noun tokens of the answer, in order. Returns [{"text", "count"}]."""
    counts: Counter[str] = Counter()
    info: dict[str, tuple[str, int, bool]] = {}
    for phrase in phrases:
        candidate = _candidate(phrase)
        if candidate is None:
            continue
        key, surface, words, proper = candidate
        counts[key] += 1
        info.setdefault(key, (surface, words, proper))  # first-seen wording, deterministic

    # A single word that only ever appears inside a longer kept phrase is redundant ("cluster" in "test cluster").
    multi = {key: counts[key] for key, (_, words, _) in info.items() if words > 1}
    redundant = set()
    for key, (_, words, _) in info.items():
        if words == 1 and any(key in other.split() and count >= counts[key] for other, count in multi.items()):
            redundant.add(key)

    def score(key: str) -> float:
        _, words, proper = info[key]
        return (1 + 0.3 * math.log(counts[key])) * (1 + 0.5 * (words - 1)) * (1.5 if proper else 1.0)

    ranked = sorted((k for k in info if k not in redundant), key=lambda k: (-score(k), k))
    return [{"text": info[k][0], "count": counts[k]} for k in ranked[:limit]]


def select_entities(raw: list[tuple[str, str]], limit: int = MAX_ENTITIES) -> list[dict]:
    """`raw`: [(text, label)] as found (duplicates allowed). Returns [{"text", "label", "count"}], unique per text."""
    per_text: dict[str, Counter[str]] = {}
    surface: dict[str, str] = {}
    for text, label in raw:
        if label not in ALLOWED_LABELS:
            continue
        cleaned = _clean(text)
        if cleaned.lower().endswith("'s"):
            cleaned = cleaned[:-2].rstrip()
        if len(cleaned) < 2 or len(cleaned) > MAX_TEXT_LENGTH or not any(ch.isalnum() for ch in cleaned):
            continue
        key = cleaned.lower()
        surface.setdefault(key, cleaned)
        per_text.setdefault(key, Counter())[label] += 1

    result = []
    for key, labels in per_text.items():
        total = sum(labels.values())
        best = min(labels, key=lambda lab: (LABEL_PRIORITY.get(lab, 99), -labels[lab], lab))
        result.append({"text": surface[key], "label": best, "count": total})
    result.sort(key=lambda e: (-e["count"], e["text"].lower()))
    return result[:limit]
