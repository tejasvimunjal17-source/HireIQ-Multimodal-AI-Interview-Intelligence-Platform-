"""NLP enrichment (Day 5): spaCy keywords + entities, VADER sentiment, rule-based confidence signal.

Context for a human reviewer only; it never changes a score or a recommendation. See service.py."""

from app.services.nlp.service import enrich, enrich_fields

__all__ = ["enrich", "enrich_fields"]
