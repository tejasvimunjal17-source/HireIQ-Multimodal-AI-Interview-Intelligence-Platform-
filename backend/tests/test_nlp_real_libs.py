"""Day 5: behaviour of the REAL spaCy model and VADER. Skipped automatically when a library or the model is not
installed (it is a separate pip package; the app never downloads it). Must run in CI after `pip install -r requirements.txt`."""

import pytest

from app.services.nlp import enrich
from app.services.nlp.spacy_backend import NlpUnavailableError
from tests.evaluation_samples import BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT, TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT
from types import SimpleNamespace

spacy = pytest.importorskip("spacy", reason="spaCy not installed")
pytest.importorskip("vaderSentiment", reason="vaderSentiment not installed")
if not spacy.util.is_package("en_core_web_sm"):
    pytest.skip("spaCy model en_core_web_sm not installed (pip install from requirements.txt)", allow_module_level=True)

SETTINGS = SimpleNamespace(nlp_enabled=True, nlp_spacy_model="en_core_web_sm")


def test_real_models_give_a_complete_enrichment_for_a_technical_answer():
    out = enrich(TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, SETTINGS)
    assert out["status"] == "completed", out["errors"]
    texts = {k["text"] for k in out["keywords"]}
    assert texts & {"process", "thread", "threads", "processes", "race conditions", "memory", "address space"}
    assert not texts & {"thing", "way", "lot"}
    assert len({k["text"] for k in out["keywords"]}) == len(out["keywords"])  # no duplicates
    assert "python" in {e["text"].lower() for e in out["entities"]}  # gazetteer
    assert out["sentiment"]["label"] in ("positive", "neutral", "negative") and -1 <= out["sentiment"]["compound"] <= 1
    assert out["models"]["spacy"].startswith("en_core_web_sm")


def test_real_models_find_a_named_organisation_and_a_date():
    text = "In March 2023 I joined Google in Berlin and migrated our reporting jobs to Kubernetes."
    out = enrich(text, BEHAVIORAL_QUESTION, SETTINGS)
    labels = {(e["text"], e["label"]) for e in out["entities"]}
    assert ("Kubernetes", "TECHNOLOGY") in labels
    assert any(label == "ORG" and "google" in t.lower() for t, label in labels)
    assert any(label == "GPE" and "berlin" in t.lower() for t, label in labels)


def test_vader_is_deterministic_and_tone_only():
    a = enrich("This was a great, successful project and I loved it.", BEHAVIORAL_QUESTION, SETTINGS)
    b = enrich("This was a great, successful project and I loved it.", BEHAVIORAL_QUESTION, SETTINGS)
    assert a["sentiment"] == b["sentiment"] and a["sentiment"]["label"] == "positive"
    dry = enrich(BEHAVIORAL_TRANSCRIPT, BEHAVIORAL_QUESTION, SETTINGS)
    assert dry["confidence"]["affects_evaluation"] is False


def test_a_missing_model_name_degrades_gracefully_instead_of_downloading():
    out = enrich(TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, SimpleNamespace(nlp_enabled=True, nlp_spacy_model="no_such_model_xyz"))
    assert out["status"] == "partial" and out["errors"]["spacy"] == "spacy_model_missing"
    assert out["sentiment"] and out["confidence"]
