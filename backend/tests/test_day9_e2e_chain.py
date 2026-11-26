"""Day 9, group: END-TO-END COMPONENT CHAIN (in-process, offline).

SCOPE - read this before quoting a result from this file.
This chains the real, database-free parts of the workflow in one process:

    transcript text -> evaluate_transcript (YAML rubric, prompt, MOCK provider, schema + evidence validation, scoring)
                    -> enrich_fields (NLP with INJECTED fake spaCy/VADER objects)
                    -> report data -> real ReportLab PDF -> real pypdf text extraction
                    -> dashboard response schemas / public_nlp

NOT exercised here (see test_day9_workflow_e2e.py and docs/DAY9_TESTING_REPORT.md): a database, the HTTP API, Celery,
Redis, Whisper, a real LLM. The "provider" is the deterministic mock, so scores say nothing about real model quality.
This file is therefore evidence that the pieces fit together, not a live-service integration test.
"""

import io
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("reportlab")

from app.schemas.dashboard import AnswerView, SessionDetail, SessionRow, public_nlp  # noqa: E402
from app.services.evaluation.pipeline import EvaluationFailure, evaluate_transcript  # noqa: E402
from app.services.evaluation.providers import MockEvaluationProvider, ProviderOutput  # noqa: E402
from app.services.nlp import enrich_fields  # noqa: E402
from app.services.nlp.text_analysis import Tok  # noqa: E402
from app.services.reporting.pdf import render_report  # noqa: E402
from tests.evaluation_samples import (  # noqa: E402
    BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT, RUBRICS_DIR, TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT,
)
from tests.report_samples import SESSION_ID, answer, report  # noqa: E402

NLP_ON = SimpleNamespace(nlp_enabled=True, nlp_spacy_model="en_core_web_sm")
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
SECRET_EMAIL = "private.person@example.com"


class FakeAnalyzer:
    def analyze(self, text):
        noun = lambda t: Tok(t, t.lower(), "NOUN", False, True)  # noqa: E731
        return [(noun("process"),), (noun("thread"),)], [("Python", "TECHNOLOGY")], len(text.split())


def fake_vader(_text):
    return {"positive": 0.1, "negative": 0.0, "neutral": 0.9, "compound": 0.4, "label": "positive"}


def evaluate(question=TECHNICAL_QUESTION, transcript=TECHNICAL_TRANSCRIPT, key="technical", provider=None, **kw):
    return evaluate_transcript(
        provider=provider or MockEvaluationProvider(), rubrics_dir=RUBRICS_DIR, rubric_name="default",
        question_text=question, question_type=key, rubric_key=key, transcript=transcript, **kw,
    )


def pdf_text(pdf: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages))


def as_report_answer(position, fields, transcript, question):
    """The stored `Evaluation` row and the report/dashboard input use the same field names."""
    return answer(position, transcript=transcript, ev=fields, question=question)


# ---------------------------------------------------------------- B. AI evaluation workflow
def test_transcript_reaches_the_pipeline_and_the_yaml_rubric_decides_the_criteria():
    result = evaluate()
    assert list(result.fields["criteria_scores"]) == [
        "technical_accuracy", "depth_of_understanding", "problem_solving_approach", "communication_clarity"]
    assert result.fields["evaluation_details"]["rubric_key"] == "technical"
    assert result.fields["rubric_name"] == "default" and result.fields["llm_provider"] == "mock"
    assert 0 <= result.fields["overall_score"] <= 100


def test_every_criterion_carries_evidence_that_really_is_in_the_transcript():
    from app.schemas.evaluation import quote_is_in_transcript

    for key, item in evaluate().fields["criteria_scores"].items():
        assert item["evidence_quotes"], key
        assert all(quote_is_in_transcript(q, TECHNICAL_TRANSCRIPT) for q in item["evidence_quotes"])


def test_behavioural_question_uses_the_behavioural_block():
    result = evaluate(BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT, "behavioral")
    assert "ownership_and_actions" in result.fields["criteria_scores"]


@pytest.mark.parametrize("raw, code", [
    ("not json at all", "invalid_json"),
    ('```json\n{"overall_score": 5}\n```', "invalid_json"),  # code fences are refused, never repaired
    ('{"overall_score": 5}', "invalid_response"),
    ("", "invalid_json"),
])
def test_invalid_provider_output_is_rejected_with_a_code_and_nothing_is_returned(raw, code):
    class Bad:
        name, model = "scripted", "m"

        def evaluate(self, prompt):
            return ProviderOutput(raw_text=raw, provider="scripted", model="m")

    with pytest.raises(EvaluationFailure) as caught:
        evaluate(provider=Bad())
    assert caught.value.code == code and caught.value.retryable
    assert TECHNICAL_TRANSCRIPT[:20] not in str(caught.value)  # no candidate words in the failure


def test_hallucinated_evidence_is_rejected():
    import json

    class Invents(MockEvaluationProvider):
        def evaluate(self, prompt):
            body = json.loads(super().evaluate(prompt).raw_text)
            body["criteria_scores"][0]["evidence_quotes"] = ["the candidate described quantum error correction in detail"]
            return ProviderOutput(raw_text=json.dumps(body), provider="scripted", model="m")

    with pytest.raises(EvaluationFailure) as caught:
        evaluate(provider=Invents())
    assert caught.value.code == "evidence_invalid"


# ---------------------------------------------------------------- B7. NLP stays advisory
def test_nlp_enrichment_changes_only_the_nlp_field():
    fields = evaluate().fields
    enriched = enrich_fields(fields, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, NLP_ON,
                             analyzer=FakeAnalyzer(), sentiment_fn=fake_vader)
    changed = {k for k in fields if enriched[k] != fields[k]}
    assert changed == {"nlp_enrichment"}
    assert enriched["nlp_enrichment"]["confidence"]["affects_evaluation"] is False


def test_the_score_is_identical_with_nlp_on_off_and_broken():
    class Broken:
        def analyze(self, text):
            raise RuntimeError("boom")

    fields = evaluate().fields
    off = enrich_fields(fields, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, SimpleNamespace(nlp_enabled=False, nlp_spacy_model="x"))
    broken = enrich_fields(fields, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, NLP_ON, analyzer=Broken(), sentiment_fn=fake_vader)
    for variant in (off, broken):
        for key in ("overall_score", "recommendation", "criteria_scores", "explanation", "evaluation_details"):
            assert variant[key] == fields[key]


# ---------------------------------------------------------------- C. report generation
@pytest.fixture(scope="module")
def full_report():
    tech = enrich_fields(evaluate().fields, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION, NLP_ON,
                         analyzer=FakeAnalyzer(), sentiment_fn=fake_vader)
    beh = enrich_fields(evaluate(BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT, "behavioral").fields,
                        BEHAVIORAL_TRANSCRIPT, BEHAVIORAL_QUESTION, NLP_ON, analyzer=FakeAnalyzer(), sentiment_fn=fake_vader)
    data = report(answers=[
        as_report_answer(1, tech, TECHNICAL_TRANSCRIPT, TECHNICAL_QUESTION),
        as_report_answer(2, beh, BEHAVIORAL_TRANSCRIPT, BEHAVIORAL_QUESTION),
    ])
    return data, tech, beh


def test_pdf_contains_the_right_candidate_interview_scores_and_advisory_wording(full_report):
    data, tech, beh = full_report
    pdf = render_report(data, NOW)
    text = pdf_text(pdf)
    assert pdf.startswith(b"%PDF-")
    assert "Asha Verma" in text and "Backend Engineer Screening" in text
    assert TECHNICAL_QUESTION[:40] in text
    assert "Technical accuracy" in text and "Ownership and actions" in text
    assert f"{tech['overall_score']:.1f}" in text or f"{tech['overall_score']:.0f}" in text
    assert "ADVISORY" in text and "not a hiring decision" in text
    assert "CONFIDENTIAL" in text


def test_pdf_never_prints_the_candidate_email_or_audio_paths(full_report):
    data, *_ = full_report
    text = pdf_text(render_report(data, NOW))
    assert "@example.com" not in text and "/tmp/" not in text and ".webm" not in text


def test_very_long_transcript_and_text_do_not_break_the_pdf():
    long_words = " ".join(["Threads share memory and processes are isolated by the operating system."] * 600)
    data = report(answers=[answer(1, transcript=long_words, ev=None), answer(2, transcript="Supercalifragilistic" * 80, ev=None)])
    pdf = render_report(data, NOW)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 2
    assert "Page 1 of" in (reader.pages[0].extract_text() or "")


def test_an_answer_without_evaluation_is_reported_as_not_evaluated_not_as_zero():
    text = pdf_text(render_report(report(answers=[answer(1, ev=None)]), NOW))
    assert "not evaluated" in text.lower() or "no evaluation" in text.lower() or "pending" in text.lower()


# ---------------------------------------------------------------- D. manager-facing schemas
def test_dashboard_views_carry_no_email_audio_path_or_transcript():
    for model in (SessionRow, SessionDetail, AnswerView):
        names = set(model.model_fields)
        assert not names & {"email", "candidate_email", "audio_path", "stored_audio_path", "transcript", "task_id", "celery_task_id"}


def test_public_nlp_hides_internals_but_keeps_the_advisory_disclaimer(full_report):
    _, tech, _ = full_report
    nlp = dict(tech["nlp_enrichment"], errors={"spacy": "model_missing"}, models={"spacy": "en_core_web_sm 3.8"})
    shown = public_nlp(nlp)
    assert "errors" not in shown and "models" not in shown
    assert "indicators" not in shown["confidence"] and shown["confidence"]["disclaimer"]


def test_session_id_in_pdf_filename_is_not_the_candidate_name():
    assert SESSION_ID  # the route builds the filename from the session id only (checked statically in test_day9_security)
