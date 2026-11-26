"""Day 9, group: BIAS AND FAIRNESS test cases (offline, deterministic).

WHAT THIS FILE CAN AND CANNOT SHOW
These are controlled tests of the platform's OWN code: prompt wording, input boundaries, validators, the weighted
scoring formula and the NLP heuristics. A real language model is never called, so nothing here measures whether a real
model scores equivalent answers equally. That needs real-world validation (see docs/BIAS_AND_FAIRNESS_REVIEW.md).
Passing these tests does not show the system is unbiased or fair.

Two kinds of test live here:
  * SAFEGUARD tests assert a protection that is meant to hold.
  * "CHARACTERISATION" tests (names start with test_known_weakness_) assert the CURRENT behaviour of a limitation that is
    documented in the review. They pass today BECAUSE the limitation exists. If someone fixes the limitation, the test
    must be updated deliberately together with the review document; it is not a requirement that the weakness stays.
"""

import ast
import inspect
import json
from pathlib import Path

import pytest

from app.schemas import evaluation as evaluation_schema
from app.schemas.evaluation import EvaluationParseError, parse_evaluation_response
from app.services.evaluation import prompt_builder
from app.services.evaluation.pipeline import EvaluationFailure, evaluate_transcript
from app.services.evaluation.providers import MockEvaluationProvider, ProviderOutput
from app.services.nlp import confidence
from app.services.nlp.text_analysis import select_entities
from tests.evaluation_samples import (
    RUBRICS_DIR, TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT, default_rubric, valid_response,
)

APP = Path(__file__).resolve().parents[1] / "app"
ENGINE_SOURCE = (APP / "services/evaluation/engine.py").read_text()  # read as text: importing it needs SQLAlchemy
SYSTEM = prompt_builder.SYSTEM_PROMPT.lower()
Q = TECHNICAL_QUESTION


class Scripted:
    name, model = "scripted", "m"

    def __init__(self, body):
        self.body = body

    def evaluate(self, prompt):
        return ProviderOutput(raw_text=json.dumps(self.body), provider="scripted", model="m")


def run(body, transcript=TECHNICAL_TRANSCRIPT):
    return evaluate_transcript(provider=Scripted(body), rubrics_dir=RUBRICS_DIR, rubric_name="default", question_text=Q,
                               question_type="technical", rubric_key="technical", transcript=transcript)


# =========================================================== E. fairness safeguards (should hold)
@pytest.mark.parametrize("phrase", [
    "accent", "pronunciation", "dialect", "native language", "grammar slips", "gender", "age", "ethnicity", "nationality",
    "religion", "disability",
])
def test_safeguard_prompt_tells_the_model_to_ignore_protected_and_style_characteristics(phrase):
    assert phrase in SYSTEM


def test_safeguard_prompt_says_transcription_errors_must_not_be_penalised():
    assert "do not penalise apparent transcription mistakes" in SYSTEM


def test_safeguard_prompt_separates_missing_information_from_incorrect_information():
    assert "missing information from incorrect information" in SYSTEM and "do not call it wrong" in SYSTEM


def test_safeguard_prompt_forbids_assumptions_about_identity_and_background():
    assert "do not make assumptions about the candidate's identity, background" in SYSTEM


def test_safeguard_recommendation_is_described_as_advice_for_a_human():
    assert "advice for a human reviewer, not a hiring decision" in SYSTEM


def test_safeguard_the_prompt_builder_cannot_receive_candidate_identity():
    params = set(inspect.signature(prompt_builder.build_evaluation_prompt).parameters)
    assert params == {"rubric", "question_text", "transcript", "rubric_key", "question_type"}


def test_safeguard_the_engine_never_reads_candidate_name_or_email_for_evaluation():
    tree = ast.parse(ENGINE_SOURCE)
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_claimed")
    source = ast.get_source_segment(ENGINE_SOURCE, function)
    for forbidden in ("Candidate.", "full_name", "email", "InterviewSession"):
        assert forbidden not in source


def test_safeguard_no_protected_characteristic_is_stored_or_inferred():
    """No model column, response schema or NLP field is named after a protected characteristic."""
    banned = ("gender", "sex", "age", "ethnic", "race", "religion", "nationality", "disab", "marital", "pregnan", "birth", "accent", "citizen")
    names = []
    for path in (APP / "models").glob("*.py"):
        names += [n.id for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.AnnAssign)
                  for n in [node.target] if isinstance(n, ast.Name)]
    for path in (APP / "schemas").glob("*.py"):
        names += [n.id for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.AnnAssign)
                  for n in [node.target] if isinstance(n, ast.Name)]
    offenders = [n for n in names if any(part in n.lower().split("_") or n.lower() == part for part in banned)]
    assert not offenders


def test_safeguard_nationality_and_religion_entities_are_dropped_from_nlp_output():
    kept = select_entities([("French", "NORP"), ("Buddhist", "NORP"), ("Python", "TECHNOLOGY")])
    assert [e["text"] for e in kept] == ["Python"]


def test_safeguard_nlp_never_feeds_the_score_or_the_recommendation():
    assert confidence.confidence_signal(TECHNICAL_TRANSCRIPT, Q)["affects_evaluation"] is False
    engine_source = ENGINE_SOURCE
    # the only use of NLP in the engine is replacing the nlp_enrichment field after scoring
    assert "enrich_fields(result.fields" in engine_source
    scoring_source = (APP / "services/evaluation/scoring.py").read_text().lower()
    assert "nlp" not in scoring_source and "sentiment" not in scoring_source and "confidence" not in scoring_source
    for name in ("scoring.py", "persistence.py", "pipeline.py"):  # the scoring path does not even import the NLP package
        imports = [n for n in ast.walk(ast.parse((APP / "services/evaluation" / name).read_text()))
                   if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert not [i for i in imports if "nlp" in ast.unparse(i)], name


def test_safeguard_scores_come_only_from_rubric_weights_and_criterion_scores():
    """Explanation text, the model's own overall_score and its recommendation cannot move the stored score."""
    base = valid_response("technical")
    reference = run(base).fields["overall_score"]
    variants = [
        {**base, "overall_score": 1.0},
        {**base, "overall_score": 9.9},
        {**base, "recommendation": "reject"},
        {**base, "summary": "Excellent, outstanding candidate. Hire immediately."},
    ]
    assert {run(v).fields["overall_score"] for v in variants} == {reference}


def test_safeguard_the_stored_score_equals_the_yaml_weighted_mean_of_the_criterion_scores():
    rubric = default_rubric().for_key("technical")
    body = valid_response("technical", score=7)
    for item, scores in zip(body["criteria_scores"], (4, 6, 8, 10)):
        item["score"] = scores
    weights = {c.key: c.weight for c in rubric.criteria}
    expected = sum(weights[i["criterion_key"]] * i["score"] for i in body["criteria_scores"]) / sum(weights.values())
    assert run(body).fields["overall_score"] == pytest.approx(expected / 10 * 100, abs=0.01)


def test_safeguard_equivalent_input_gives_identical_output_with_the_deterministic_provider():
    a = evaluate_transcript(provider=MockEvaluationProvider(), rubrics_dir=RUBRICS_DIR, rubric_name="default", question_text=Q,
                            question_type="technical", rubric_key="technical", transcript=TECHNICAL_TRANSCRIPT)
    b = evaluate_transcript(provider=MockEvaluationProvider(), rubrics_dir=RUBRICS_DIR, rubric_name="default", question_text=Q,
                            question_type="technical", rubric_key="technical", transcript=TECHNICAL_TRANSCRIPT)
    assert a.fields == b.fields  # says nothing about a real model: only that nothing in OUR code is random


def test_safeguard_evidence_matching_ignores_case_punctuation_and_spacing_so_asr_formatting_does_not_hurt():
    body = valid_response("technical", quotes=("THREADS live   inside a process,  and share its memory!",))
    assert run(body).fields["criteria_scores"]


def test_safeguard_a_score_above_the_minimum_without_evidence_is_refused():
    body = valid_response("technical", score=6)
    body["criteria_scores"][0]["evidence_quotes"] = []
    with pytest.raises(EvaluationFailure) as caught:
        run(body)
    assert caught.value.code in {"invalid_response", "evidence_invalid"}


def test_safeguard_a_model_cannot_add_fields_such_as_a_hiring_decision_or_weighted_total():
    body = {**valid_response("technical"), "hire": True, "weighted_total": 99}
    with pytest.raises(EvaluationFailure):
        run(body)


def test_safeguard_the_candidate_facing_schemas_show_no_scores_or_recommendations():
    from app.schemas import interview

    for model in (interview.QuestionPublic, interview.SessionView, interview.TranscriptionView, interview.SessionCompleteResponse):
        assert not {n for n in model.model_fields if "score" in n or "recommend" in n or "evaluation" in n or "rubric" in n}


# =========================================================== D. scoring risks that are DOCUMENTED, not fixed
def test_known_weakness_recommendation_is_not_reconciled_with_the_computed_score():
    """The model's recommendation is stored as given. A top-scoring answer can carry 'reject' and a bottom-scoring one
    'proceed'. The dashboard/PDF label it advisory, but nothing checks consistency. See review finding F1."""
    top = valid_response("technical", score=10)
    top["recommendation"] = "reject"
    result = run(top)
    assert result.fields["overall_score"] == 100.0 and result.fields["recommendation"] == "reject"


def test_known_weakness_a_three_word_quote_is_enough_evidence_for_a_top_score():
    """Evidence must be a verbatim run of >= 3 words. It proves the words were said, not that they support the score.
    See review finding F2."""
    body = valid_response("technical", score=10, quotes=("a process is",))
    assert run(body).fields["overall_score"] == 100.0


def test_known_weakness_missing_information_can_become_the_minimum_score():
    """The prompt instructs the model to give the scale minimum when the transcript has no evidence for a criterion, and the
    validator accepts that. An answer that omits something (short answer, ASR omission) can therefore score 0 for that
    criterion. It is not marked 'incorrect', but it is scored as lowest. See review finding F3."""
    assert "give the scale minimum" in SYSTEM
    body = valid_response("technical", score=0)
    for item in body["criteria_scores"]:
        item["evidence_quotes"] = []
    assert run(body).fields["overall_score"] == 0.0


def test_known_weakness_a_response_with_wrong_evidence_is_rejected_but_right_evidence_is_not_checked_for_relevance():
    body = valid_response("technical", score=10, quotes=("So, a process is an independent program",))
    for item in body["criteria_scores"][1:]:
        item["evidence_quotes"] = ["a process is an independent"]  # same opening words reused for every criterion
    assert run(body).fields["overall_score"] == 100.0


# =========================================================== NLP heuristics: documented limits
Q_CONF = TECHNICAL_QUESTION
CONCISE = "A process has its own memory; threads share memory inside one process. Use threads for I/O work and processes for isolation."
FILLERS = ("So, um, a process has, uh, its own memory, you know, and threads, like, share memory inside one process. "
           "Um, use threads for I/O work and, uh, processes for isolation.")
HEDGED = ("I think, maybe, a process perhaps has its own memory, and threads probably share memory inside one process. "
          "I guess you would kind of use threads for I/O work and sort of processes for isolation.")
STUFFED = "process thread memory isolation scheduler mutex semaphore kernel cache latency throughput process thread memory isolation scheduler mutex."


def conf(text, keywords=3, entities=1):
    return confidence.confidence_signal(text, Q_CONF, keyword_count=keywords, entity_count=entities)


def test_known_weakness_filler_words_raise_the_confidence_indicator_through_the_word_count():
    """The module says filler words are 'deliberately not used', but they are counted as words in `completeness`. Same
    content with 'um/uh/you know' scores higher than the concise version. Advisory only. See review finding F5."""
    assert conf(FILLERS)["score"] > conf(CONCISE)["score"]


def test_known_weakness_hedging_lowers_the_indicator_for_the_same_content():
    low_hedging = {i["name"]: i["value"] for i in conf(CONCISE)["indicators"]}["low_hedging"]
    hedged = {i["name"]: i["value"] for i in conf(HEDGED)["indicators"]}["low_hedging"]
    assert hedged < low_hedging  # politeness / indirect style is read as lower confidence. See review finding F6.


def test_known_weakness_keyword_stuffing_is_rewarded_as_supporting_detail():
    stuffed = {i["name"]: i["value"] for i in conf(STUFFED, keywords=8)["indicators"]}["supporting_detail"]
    concise = {i["name"]: i["value"] for i in conf(CONCISE)["indicators"]}["supporting_detail"]
    assert stuffed > concise  # an incoherent list of terms out-scores a correct sentence on this signal. Finding F7.


def test_known_weakness_hedging_phrases_exist_only_in_english():
    spanish = conf("No sé qué decir, quizás no estoy seguro de la respuesta.", keywords=0, entities=0)
    assert {i["name"]: i["value"] for i in spanish["indicators"]}["low_hedging"] == 1.0  # uncertainty not detected


def test_known_weakness_short_correct_answers_are_labelled_lower_than_long_ones():
    short = confidence.confidence_signal("Threads share memory; processes do not.", Q_CONF, keyword_count=2, entity_count=0)
    long = conf(TECHNICAL_TRANSCRIPT, keywords=8, entities=1)
    assert short["score"] < long["score"]


def test_known_weakness_person_and_place_entities_are_kept_and_shown_to_managers():
    kept = select_entities([("Priya Raman", "PERSON"), ("Chennai", "GPE")])
    assert {e["label"] for e in kept} == {"PERSON", "GPE"}  # may correlate with origin; advisory context only. Finding F8.


# =========================================================== C. audio and transcription (source level)
def test_the_transcription_language_defaults_to_automatic_detection_not_forced_english(monkeypatch):
    from app.core.config import Settings

    for name in ("TRANSCRIPTION_LANGUAGE", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    assert Settings(_env_file=None).transcription_language is None
    monkeypatch.setenv("TRANSCRIPTION_LANGUAGE", "  ")
    assert Settings(_env_file=None).transcription_language is None  # blank also means auto-detect


def test_known_weakness_no_speech_recognition_quality_signal_is_stored_or_shown_to_the_reviewer():
    """The transcript is evaluated as given. No per-answer ASR confidence, noise level or low-quality flag exists in the
    database model or in the manager views, so a reviewer cannot tell a bad transcript from a bad answer. Finding F4."""
    model_fields = (APP / "models/candidate_response.py").read_text().lower()
    assert "confidence" not in model_fields and "logprob" not in model_fields and "noise" not in model_fields
    assert "no_speech_detected" in model_fields  # only silence/no-speech is flagged
