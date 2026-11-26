"""The ONLY place that imports spaCy (Day 5). Loads the installed model and turns a document into the plain
records used by text_analysis.py.

- The model is loaded lazily, once per worker process, from the pip-installed package named by NLP_SPACY_MODEL.
  It is NEVER downloaded here: a missing model raises NlpUnavailableError("spacy_model_missing").
- The loaded model holds no candidate data; every call analyses one transcript and keeps nothing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.services.nlp.text_analysis import TECHNOLOGY_TERMS, Tok


class NlpUnavailableError(RuntimeError):
    """An NLP library or model is not installed. `code` is a short machine code (safe to store and log)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=2)
def _load(model_name: str) -> tuple[Any, Any, str]:
    try:
        import spacy
        from spacy.matcher import PhraseMatcher
    except ImportError:
        raise NlpUnavailableError("spacy_not_installed", "spaCy is not installed.") from None
    try:
        nlp = spacy.load(model_name)
    except OSError:
        raise NlpUnavailableError(
            "spacy_model_missing",
            f"The spaCy model '{model_name}' is not installed. Install it with pip (see requirements.txt).",
        ) from None
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    matcher.add("TECHNOLOGY", [nlp.make_doc(term) for term in TECHNOLOGY_TERMS])
    version = str(getattr(nlp, "meta", {}).get("version", ""))
    return nlp, matcher, f"{model_name} {version}".strip()


def model_label(model_name: str) -> str:
    return _load(model_name)[2]


def _tok(token: Any) -> Tok:
    return Tok(text=token.text, lemma=token.lemma_ or token.text, pos=token.pos_, is_stop=bool(token.is_stop),
               is_alpha=bool(token.is_alpha))


class SpacyAnalyzer:
    """analyze(text) -> (phrases, entities, word_count) for text_analysis.select_keywords / select_entities."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name

    def analyze(self, text: str) -> tuple[list[tuple[Tok, ...]], list[tuple[str, str]], int]:
        nlp, matcher, _ = _load(self._model_name)
        doc = nlp(text)
        phrases: list[tuple[Tok, ...]] = [tuple(_tok(t) for t in chunk) for chunk in doc.noun_chunks]
        phrases += [(_tok(t),) for t in doc if t.pos_ in ("NOUN", "PROPN")]
        entities = [(ent.text, ent.label_) for ent in doc.ents]
        entities += [(doc[start:end].text, "TECHNOLOGY") for _, start, end in matcher(doc)]
        word_count = sum(1 for t in doc if t.is_alpha or t.like_num)
        return phrases, entities, word_count
