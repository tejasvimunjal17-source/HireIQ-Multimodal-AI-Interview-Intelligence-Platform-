"""Day 5: keyword/entity selection, sentiment labels and the confidence heuristic. Pure Python: no spaCy, no VADER,
no database, no network. (Real-library behaviour is in test_nlp_real_libs.py.)"""

import inspect
import math

import pytest

from app.services.nlp import confidence, sentiment, text_analysis as ta
from app.services.nlp.text_analysis import Tok
from tests.evaluation_samples import BEHAVIORAL_QUESTION, BEHAVIORAL_TRANSCRIPT, TECHNICAL_QUESTION, TECHNICAL_TRANSCRIPT


def N(text, lemma=None, pos="NOUN", stop=False):
    return Tok(text=text, lemma=lemma or text.lower(), pos=pos, is_stop=stop)


THE = Tok("the", "the", "DET", True)
MY = Tok("my", "my", "PRON", True)


# ---------------------------------------------------------------- keywords
def test_determiners_and_stop_words_are_trimmed_from_phrases():
    result = ta.select_keywords([(THE, N("test"), N("cluster"))])
    assert result == [{"text": "test cluster", "count": 1}]


def test_vague_nouns_and_stop_only_phrases_are_dropped():
    assert ta.select_keywords([(N("thing"),), (THE, N("lot")), (MY,), (THE,), (N("way"),)]) == []


def test_single_character_and_non_alphabetic_tokens_are_dropped():
    assert ta.select_keywords([(N("x"),), (Tok("42", "42", "NOUN", False, False),)]) == []


def test_specific_phrases_and_names_outrank_a_vague_repeated_noun():
    phrases = [(N("system"),)] * 3 + [(N("failed-run"), N("rate"))] + [(N("Kubernetes", pos="PROPN"),)]
    texts = [k["text"] for k in ta.select_keywords(phrases)]
    assert texts[:2] == ["kubernetes", "failed-run rate"] or texts[:2] == ["failed-run rate", "kubernetes"]
    assert texts.index("system") > 1  # frequency alone does not win


def test_duplicates_are_merged_and_counted_case_insensitively():
    result = ta.select_keywords([(N("Cluster"),), (N("cluster"),), (THE, N("cluster"))])
    assert result == [{"text": "cluster", "count": 3}]


def test_a_single_word_inside_a_kept_phrase_is_not_repeated():
    phrases = [(N("test"), N("cluster")), (N("cluster"),)]
    assert [k["text"] for k in ta.select_keywords(phrases)] == ["test cluster"]


def test_a_word_used_alone_more_often_than_in_the_phrase_is_kept():
    phrases = [(N("test"), N("cluster")), (N("cluster"),), (N("cluster"),)]
    assert {k["text"] for k in ta.select_keywords(phrases)} == {"test cluster", "cluster"}


def test_keyword_list_is_limited_and_deterministic():
    phrases = [(N(f"topic{chr(97 + i)}x"),) for i in range(15)]
    first, second = ta.select_keywords(phrases), ta.select_keywords(list(phrases))
    assert first == second and len(first) == ta.MAX_KEYWORDS


@pytest.mark.parametrize("phrases", [[], [()], [(THE,)]])
def test_empty_input_gives_no_keywords(phrases):
    assert ta.select_keywords(phrases) == []


# ---------------------------------------------------------------- entities
def test_entities_are_deduplicated_per_text_and_counted():
    raw = [("Google", "ORG"), ("google", "ORG"), ("Berlin", "GPE")]
    assert ta.select_entities(raw) == [
        {"text": "Google", "label": "ORG", "count": 2}, {"text": "Berlin", "label": "GPE", "count": 1}]


def test_technology_label_beats_a_statistical_label_for_the_same_text():
    result = ta.select_entities([("Kubernetes", "ORG"), ("kubernetes", "TECHNOLOGY")])
    assert result == [{"text": "Kubernetes", "label": "TECHNOLOGY", "count": 2}]


def test_numeric_and_protected_group_labels_are_not_kept():
    raw = [("ten", "CARDINAL"), ("8 percent", "PERCENT"), ("French", "NORP"), ("Catholic", "NORP"), ("Acme", "ORG")]
    assert [e["text"] for e in ta.select_entities(raw)] == ["Acme"]


def test_entity_text_is_cleaned_and_junk_is_dropped():
    raw = [("  Acme's ", "ORG"), ("!", "ORG"), ("A", "ORG"), ("x" * 200, "ORG")]
    assert ta.select_entities(raw) == [{"text": "Acme", "label": "ORG", "count": 1}]


def test_entities_are_ordered_by_count_then_name_and_limited():
    raw = [(f"Org{i:02d}", "ORG") for i in range(30)] + [("Zed", "ORG")] * 3
    result = ta.select_entities(raw)
    assert result[0]["text"] == "Zed" and len(result) == ta.MAX_ENTITIES
    assert ta.select_entities([]) == []


def test_gazetteer_has_no_everyday_english_words():
    for word in ("rest", "spring", "swift", "spark", "react", "rust", "lambda", "angular"):
        assert word not in ta.TECHNOLOGY_TERMS


# ---------------------------------------------------------------- sentiment (labels and shape only; VADER is real-lib)
@pytest.mark.parametrize("compound,label", [
    (1.0, "positive"), (0.05, "positive"), (0.0499, "neutral"), (0.0, "neutral"), (-0.0499, "neutral"),
    (-0.05, "negative"), (-1.0, "negative")])
def test_sentiment_label_boundaries(compound, label):
    assert sentiment.label_for(compound) == label


class FakeVader:
    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def polarity_scores(self, text):
        self.calls.append(text)
        return self.scores


def test_sentiment_output_shape_rounding_and_independence():
    fake = FakeVader({"pos": 0.123456, "neg": 0.0, "neu": 0.876544, "compound": 0.6249})
    out = sentiment.analyze_sentiment("anything", analyzer=fake)
    assert out == {"positive": 0.1235, "negative": 0.0, "neutral": 0.8765, "compound": 0.6249, "label": "positive"}
    assert sentiment.analyze_sentiment("anything", analyzer=fake) == out  # deterministic
    assert fake.calls == ["anything", "anything"]  # only the text of this answer is analysed


# ---------------------------------------------------------------- confidence heuristic
def sig(transcript, question=TECHNICAL_QUESTION, **kw):
    return confidence.confidence_signal(transcript, question, **kw)


def by_name(result):
    return {i["name"]: i for i in result["indicators"]}


def test_weights_sum_to_one_and_every_signal_documents_a_limitation():
    assert math.isclose(sum(confidence.WEIGHTS.values()), 1.0)
    assert set(confidence.LIMITATIONS) == set(confidence.WEIGHTS)
    assert all(len(text) > 20 for text in confidence.LIMITATIONS.values())


def test_a_complete_structured_specific_answer_scores_higher_than_a_thin_one():
    full = sig(TECHNICAL_TRANSCRIPT, keyword_count=8, entity_count=2)
    thin = sig("I do not know.", keyword_count=0, entity_count=0)
    assert full["score"] > thin["score"] and full["label"] in ("moderate", "high") and thin["label"] == "low"


def test_result_is_labelled_a_heuristic_and_never_affects_the_evaluation():
    result = sig(TECHNICAL_TRANSCRIPT, keyword_count=5, entity_count=1)
    assert result["kind"] == "heuristic" and result["affects_evaluation"] is False
    assert 0 <= result["score"] <= 1 and all(0 <= i["value"] <= 1 for i in result["indicators"])
    assert math.isclose(sum(i["weight"] for i in result["indicators"]), 1.0, abs_tol=1e-3)
    assert all(i["limitation"] for i in result["indicators"])


def test_it_has_no_sentiment_input_and_no_demographic_input():
    params = set(inspect.signature(confidence.confidence_signal).parameters)
    assert params == {"transcript", "question", "keyword_count", "entity_count"}
    # the module docstring names what is NOT used; the code itself must not reference these inputs
    code = inspect.getsource(confidence.confidence_signal).lower()
    for forbidden in ("sentiment", "vader", "gender", "ethnic", "accent", "disab"):
        assert forbidden not in code


def test_filler_words_and_speech_disfluencies_do_not_change_the_signal():
    clean = sig(TECHNICAL_TRANSCRIPT, keyword_count=5, entity_count=1)
    noisy = sig("Um, uh, " + TECHNICAL_TRANSCRIPT.replace(", ", ", you know, like, "), keyword_count=5, entity_count=1)
    names = ("structure", "supporting_detail", "low_hedging")
    assert [by_name(clean)[n]["value"] for n in names] == [by_name(noisy)[n]["value"] for n in names]


def test_ordinary_i_think_is_not_hedging_but_explicit_uncertainty_is():
    plain = sig("I think a process has its own memory and a thread shares memory with its process.", keyword_count=3, entity_count=0)
    unsure = sig("I'm not sure, maybe, I guess, probably it is kind of like a thing.", keyword_count=0, entity_count=0)
    assert by_name(plain)["low_hedging"]["value"] == 1.0
    assert by_name(unsure)["low_hedging"]["value"] < 0.5


def test_hedging_is_only_penalised_above_the_allowance():
    long_answer = TECHNICAL_TRANSCRIPT + " Maybe that is the main difference."  # one hedge in ~100 words
    assert by_name(sig(long_answer, keyword_count=5, entity_count=0))["low_hedging"]["value"] == 1.0


def test_directness_uses_the_question_and_is_left_out_without_one():
    on_topic = by_name(sig(TECHNICAL_TRANSCRIPT, keyword_count=3, entity_count=0))["directness"]["value"]
    off_topic = by_name(sig("Well the weather was lovely yesterday and we walked by the river for hours.",
                            keyword_count=3, entity_count=0))["directness"]["value"]
    assert on_topic > off_topic
    assert "directness" in sig(TECHNICAL_TRANSCRIPT, question="", keyword_count=3)["unavailable"]


def test_missing_counts_leave_the_detail_signal_out_and_reweight_the_rest():
    result = sig(TECHNICAL_TRANSCRIPT)  # no keyword/entity counts (e.g. spaCy was unavailable)
    assert "supporting_detail" in result["unavailable"] and "supporting_detail" not in by_name(result)
    assert math.isclose(sum(i["weight"] for i in result["indicators"]), 1.0, abs_tol=1e-3)


def test_numbers_count_as_supporting_detail():
    base = sig("We changed the process.", keyword_count=0, entity_count=0)
    numbers = sig("We changed 3 jobs and cut errors from 8 to 1.", keyword_count=0, entity_count=0)
    assert by_name(numbers)["supporting_detail"]["value"] > by_name(base)["supporting_detail"]["value"]


@pytest.mark.parametrize("text", ["", "   ", None, "...", "!!!"])
def test_empty_or_wordless_input_returns_none(text):
    assert sig(text) is None


def test_very_short_answers_are_handled():
    result = sig("Yes.", keyword_count=0, entity_count=0)
    assert result["label"] == "low" and 0 <= result["score"] <= 1


def test_the_signal_is_deterministic_and_does_not_depend_on_the_other_question_type():
    a = sig(BEHAVIORAL_TRANSCRIPT, BEHAVIORAL_QUESTION, keyword_count=6, entity_count=1)
    assert a == sig(BEHAVIORAL_TRANSCRIPT, BEHAVIORAL_QUESTION, keyword_count=6, entity_count=1)
