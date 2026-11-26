"""NLP enrichment orchestrator (Day 5). Entry points: `enrich()` and `enrich_fields()`.

    transcript + question ─┬─ spaCy  → keywords, entities
                           ├─ VADER  → sentiment
                           └─ rules  → confidence signal (uses the keyword/entity COUNTS, never the sentiment)
                                  ↓
                       NlpEnrichment (validated) → plain JSON dict → evaluations.nlp_enrichment

Guarantees
- `enrich` NEVER raises. Each component runs on its own: one failing (missing model, library error) is recorded as
  a short code in `errors` and the others still run (status "partial"; "failed" if all fail).
- Candidate text is never logged: only counts, status and exception CLASS names.
- It cannot change the Day 4 result: `enrich_fields` only replaces the `nlp_enrichment` key of the fields dict
  (score, recommendation, criteria and explanation are copied through untouched).
- Disabled (NLP_ENABLED=false) -> None, i.e. the column stays NULL as before Day 5.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.schemas.nlp import NlpEnrichment
from app.services.nlp import confidence, sentiment, text_analysis
from app.services.nlp.spacy_backend import NlpUnavailableError, SpacyAnalyzer, model_label

logger = logging.getLogger(__name__)


def _code(exc: Exception) -> str:
    return exc.code if isinstance(exc, NlpUnavailableError) else "analysis_error"


def _failed_marker(word_count: int, errors: dict[str, str]) -> dict:
    return {"schema_version": 1, "status": "failed", "word_count": word_count, "errors": errors}


def enrich(
    transcript: str,
    question_text: str,
    settings: Any,
    *,
    analyzer: Any = None,
    sentiment_fn: Callable[[str], dict] | None = None,
) -> dict | None:
    """Return the dict to store in `nlp_enrichment`, or None when NLP is disabled. Never raises."""
    if not getattr(settings, "nlp_enabled", True):
        return None
    text = transcript.strip() if isinstance(transcript, str) else ""
    words = len(text.split())
    try:
        if not text:
            return NlpEnrichment(status="skipped", word_count=0, errors={"transcript": "empty_transcript"}).model_dump(mode="json")

        errors: dict[str, str] = {}
        models: dict[str, str] = {}
        keywords = entities = sent = None
        word_count = words

        try:
            analyzer = analyzer or SpacyAnalyzer(settings.nlp_spacy_model)
            phrases, raw_entities, word_count = analyzer.analyze(text)
            keywords = text_analysis.select_keywords(phrases)
            entities = text_analysis.select_entities(raw_entities)
            if isinstance(analyzer, SpacyAnalyzer):
                models["spacy"] = model_label(settings.nlp_spacy_model)
        except Exception as exc:  # noqa: BLE001 - a broken NLP step must not reach the evaluation
            errors["spacy"] = _code(exc)
            logger.warning("NLP spaCy step failed code=%s error=%s", errors["spacy"], type(exc).__name__)

        try:
            sent = (sentiment_fn or sentiment.analyze_sentiment)(text)
        except Exception as exc:  # noqa: BLE001
            errors["sentiment"] = _code(exc)
            logger.warning("NLP sentiment step failed code=%s error=%s", errors["sentiment"], type(exc).__name__)

        conf = None
        try:
            conf = confidence.confidence_signal(
                text, question_text,
                keyword_count=None if keywords is None else len(keywords),
                entity_count=None if entities is None else len(entities),
            )
        except Exception as exc:  # noqa: BLE001
            errors["confidence"] = _code(exc)
            logger.warning("NLP confidence step failed code=%s error=%s", errors["confidence"], type(exc).__name__)

        done = sum(part is not None for part in (keywords, sent, conf))
        status = "failed" if done == 0 else "partial" if errors else "completed"
        result = NlpEnrichment(
            status=status, word_count=word_count, keywords=keywords, entities=entities, sentiment=sent,
            confidence=conf, errors=errors, models=models,
        ).model_dump(mode="json")
        logger.info("NLP enrichment status=%s words=%d errors=%s", status, word_count, sorted(errors))
        return result
    except Exception as exc:  # noqa: BLE001 - includes output validation errors
        logger.error("NLP enrichment failed error=%s", type(exc).__name__)
        return _failed_marker(words, {"nlp": "internal_error"})


def enrich_fields(fields: dict, transcript: str, question_text: str, settings: Any, **kwargs: Any) -> dict:
    """Copy of an evaluation `fields` dict (see evaluation.persistence) with `nlp_enrichment` filled in.

    Only that one key changes. Used by the engine after the LLM result is fully validated and scored."""
    try:
        enrichment = enrich(transcript, question_text, settings, **kwargs)
    except Exception as exc:  # noqa: BLE001 - belt and braces: enrich() should never raise
        logger.error("NLP enrichment crashed error=%s", type(exc).__name__)
        enrichment = _failed_marker(0, {"nlp": "internal_error"})
    return {**fields, "nlp_enrichment": enrichment}
