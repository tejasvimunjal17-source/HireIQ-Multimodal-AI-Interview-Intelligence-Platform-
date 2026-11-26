"""Day 6: PDF report generator (pure ReportLab code: no database, no network, no model). Real code, real PDFs."""

import io
import re
import shutil
import subprocess

import pytest

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("reportlab")

from app.services.reporting import pdf as pdf_module  # noqa: E402
from app.services.reporting.data import build_answer  # noqa: E402
from app.services.reporting.pdf import MARGIN_X, PAGE_W, render_report  # noqa: E402
from app.services.reporting.radar import aggregate_criteria, radar_drawing  # noqa: E402
from tests.report_samples import BK, NOW, SESSION_ID, TK, answer, evaluation, report  # noqa: E402


def make_pdf(data=None) -> bytes:
    return render_report(data if data is not None else report(), NOW)


def pages(pdf: bytes) -> list[str]:
    return [p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages]


def text(pdf: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(pages(pdf)))


# ------------------------------------------------------------------ structure
def test_valid_pdf_with_title_and_footer_on_every_page():
    pdf = make_pdf()
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    ps = pages(pdf)
    assert "Candidate Interview Evaluation Report" in ps[0] and "HireIQ" in ps[0]
    for number, page in enumerate(ps, 1):
        assert f"Page {number} of {len(ps)}" in page
        assert "CONFIDENTIAL" in page


def test_generation_is_deterministic_for_the_same_time():
    assert text(make_pdf()) == text(make_pdf())


def test_candidate_and_interview_details():
    t = text(make_pdf())
    for expected in ("Asha Verma", "Backend Engineer Screening", SESSION_ID, "c1c1c1c1-0000-1111-2222-333344445555", "20 Nov 2026"):
        assert expected in t


def test_missing_optional_candidate_info_is_left_out_not_invented():
    t = text(make_pdf(report(candidate_name=None, interview_title=None, interview_date=None, candidate_id=None)))
    assert "Candidate Interview Evaluation Report" in t
    assert "None" not in t and "N/A" not in t and "Asha" not in t


def test_overall_score_is_the_exact_stored_value():
    t = text(make_pdf(report(stored_overall_score=71.25, stored_recommendation="proceed")))
    assert "71.25" in t and "/ 100" in t


def test_average_is_labelled_when_no_session_score_is_stored():
    t = text(make_pdf())
    assert "69.75" in t and "Average of 2 evaluated answers" in t


def test_stored_recommendation_is_shown_and_never_regenerated():
    t = text(make_pdf(report(stored_overall_score=90, stored_recommendation="reject")))
    assert "REJECT" in t.upper()
    # the stored value wins even though the per-answer scores are high
    assert "advisory" in t.lower() and "not a hiring decision" in t


def test_no_session_recommendation_says_so():
    assert "No session-level recommendation is stored" in text(make_pdf())


def test_per_question_and_criterion_breakdown():
    t = text(make_pdf())
    for expected in ("Question text 1?", "Question text 2?", "75.5", "64", "Technical accuracy", "Reflection and learning",
                     "Explanation for technical_accuracy.", "threads share memory", "Threads share memory."):
        assert expected in t


def test_criterion_scores_are_not_rounded_away():
    t = text(make_pdf(report([answer(ev=evaluation(scores=(7.25, 6, 8, 9), overall=70.125))])))
    assert "7.25" in t and "70.12" in t.replace("70.13", "70.12")


# ------------------------------------------------------------------ transcript / pagination / escaping
def test_long_transcript_paginates_without_text_outside_margins():
    long = ("Threads share memory and processes do not. " * 600) + "END_OF_TRANSCRIPT"
    pdf = make_pdf(report([answer(transcript=long, ev=evaluation())]))
    assert len(pages(pdf)) >= 4 and "END_OF_TRANSCRIPT" in text(pdf)
    if shutil.which("pdftotext"):  # exact word boxes (poppler); otherwise only the text/pagination checks above run
        out = subprocess.run(["pdftotext", "-bbox", "-", "-"], input=pdf, capture_output=True, check=True).stdout.decode()
        boxes = [(float(a), float(b)) for a, b in re.findall(r'xMin="([\d.]+)" yMin="[\d.]+" xMax="([\d.]+)"', out)]
        assert boxes and min(a for a, _ in boxes) >= MARGIN_X - 2 and max(b for _, b in boxes) <= PAGE_W - MARGIN_X + 2


def test_unbroken_400_character_token_is_not_clipped():
    token = "X" * 400
    t = text(make_pdf(report([answer(transcript=f"start {token} finish", ev=evaluation())]))).replace(" ", "")
    assert token in t and "finish" in t


def test_html_and_markup_in_transcript_renders_literally():
    nasty = "<b>bold</b> & <script>alert(1)</script> <font size=99>big</font> <img src='x'/> </para> &amp;"
    t = text(make_pdf(report([answer(transcript=nasty, ev=evaluation())])))
    for literal in ("<b>bold</b>", "<script>alert(1)</script>", "<font size=99>big</font>", "&amp;"):
        assert literal in t


def test_markup_in_names_questions_and_explanations_is_escaped_too():
    ev = evaluation()
    ev["explanation"] = "<b>x</b> & y"
    data = report([answer(ev=ev, question="<i>Q</i>?")], candidate_name="<u>Eve</u> & Co")
    t = text(make_pdf(data))
    assert "<u>Eve</u> & Co" in t and "<i>Q</i>?" in t and "<b>x</b> & y" in t


def test_control_characters_are_removed_and_unicode_kept():
    t = text(make_pdf(report([answer(transcript="café naïve \x00\x07\x1b[31m red ‮", ev=evaluation())])))
    assert "café naïve" in t and "\x00" not in t and "\x1b" not in t and "‮" not in t


def test_unsupported_glyphs_are_counted_and_noted_not_crashing():
    t = text(make_pdf(report([answer(transcript="hello 中文 world", ev=evaluation())])))
    assert "could not be drawn with the report font" in t


# ------------------------------------------------------------------ incomplete / empty / malformed data
def test_partial_report_is_marked_and_lists_reasons():
    data = report([
        answer(1, ev=evaluation()),
        answer(2, transcript="", transcription_status="completed", no_speech=True, evaluation_status="skipped", evaluation_error="no_speech"),
        answer(3, transcript=None, transcription_status="processing"),
        answer(4, answered=False),
    ])
    t = text(make_pdf(data))
    assert "PARTIAL REPORT" in t and "1 of 4" in t
    assert "No speech was detected" in t and "Transcription not finished yet" in t and "No answer was recorded" in t


def test_report_with_no_evaluated_answer_still_renders_a_safe_pdf():
    t = text(make_pdf(report([answer(1, transcript=None, transcription_status="pending")])))
    assert "PARTIAL REPORT" in t and "Average of" not in t


def test_malformed_evaluation_json_never_crashes_and_invents_nothing():
    bad = {
        "overall_score": 50, "recommendation": "maybe", "explanation": 123,
        "criteria_scores": {"a": "oops", "b": {"score": "NaN"}, "c": {"score": 99}, "d": None, "e": {"score": 5, "evidence_quotes": "str"}},
        "evaluation_details": ["not", "a", "dict"], "nlp_enrichment": {"status": "completed", "garbage": True},
    }
    a = build_answer({"position": 1, "question": "Q", "transcript": "t", "transcription_status": "completed",
                      "evaluation_status": "completed", "evaluation": bad})
    assert a.recommendation is None and a.nlp is None and a.issues
    assert {c.key for c in a.criteria} <= {"c", "e"}  # no scale is stored, so 99 cannot be range-checked; a/b/d are unusable
    scaled = build_answer({"position": 1, "question": "Q", "evaluation": {"overall_score": 50, "criteria_scores": bad["criteria_scores"],
                           "evaluation_details": {"score_scale": {"min": 0, "max": 10}}}})
    assert {c.key for c in scaled.criteria} == {"e"} and scaled.issues
    assert "50" in text(make_pdf(report([answer(ev=bad)])))


def test_empty_session_renders_without_crash():
    assert text(make_pdf(report([]))).count("Candidate Interview Evaluation Report") >= 1


def test_overall_score_out_of_range_is_not_displayed_as_a_score():
    a = build_answer({"position": 1, "question": "Q", "evaluation": {"overall_score": 150, "criteria_scores": {}}})
    assert not a.is_evaluated


# ------------------------------------------------------------------ NLP
def test_nlp_section_is_labelled_experimental_and_advisory():
    t = text(make_pdf())
    assert "EXPERIMENTAL" in t and "does not affect the recommendation" in t


def test_missing_nlp_is_marked_unavailable_not_fabricated():
    data = report([answer(ev=evaluation(nlp=None))])
    t = text(make_pdf(data))
    assert "unavailable" in t.lower() and "Sentiment (VADER)" not in t


def test_failed_nlp_enrichment_is_not_shown_as_results():
    data = report([answer(ev=evaluation(nlp={"schema_version": 1, "status": "failed", "errors": {"x": "boom"}}))])
    assert "Sentiment (VADER)" not in text(make_pdf(data))


def test_sentiment_and_confidence_do_not_change_stored_decision():
    base = make_pdf(report(stored_overall_score=60, stored_recommendation="hold"))
    changed_nlp = dict(__import__("tests.report_samples", fromlist=["NLP"]).NLP)
    changed_nlp["sentiment"] = {**changed_nlp["sentiment"], "compound": -0.9, "label": "negative"}
    changed_nlp["confidence"] = {**changed_nlp["confidence"], "score": 0.05, "label": "low"}
    other = make_pdf(report([answer(1, ev=evaluation(nlp=changed_nlp)), answer(2, ev=evaluation(BK, (6, 7, 8, 5), 64, "hold"))],
                            stored_overall_score=60, stored_recommendation="hold"))
    for t in (text(base), text(other)):
        assert "HOLD" in t.upper() and "60" in t


# ------------------------------------------------------------------ radar
def _answers(*evs):
    return tuple(build_answer({"position": i, "question": "Q", "evaluation": ev}) for i, ev in enumerate(evs, 1))


def test_radar_aggregation_is_the_plain_mean_per_criterion():
    radar, reason = aggregate_criteria(_answers(evaluation(TK, (8, 6, 4, 10)), evaluation(TK, (6, 6, 8, 0))))
    assert radar is not None and reason == ""
    values = {p.key: p.value for p in radar.points}
    assert values == {"technical_accuracy": 7.0, "depth_of_understanding": 6.0, "problem_solving_approach": 6.0, "communication_clarity": 5.0}
    assert radar.scale == (0, 10) and all(p.answers == 2 for p in radar.points)


def test_radar_does_not_fabricate_missing_criteria_scores():
    radar, _ = aggregate_criteria(_answers(evaluation(TK, (8, 6, 4, 10)), evaluation(BK[:3] + TK[:1], (5, 5, 5, 2))))
    counts = {p.key: p.answers for p in radar.points}
    assert counts["technical_accuracy"] == 2 and counts["communication_clarity"] == 1 and counts["results_and_impact"] == 1
    assert {p.key: p.value for p in radar.points}["communication_clarity"] == 10  # not averaged with a made-up 0


def test_radar_skips_unevaluated_answers():
    pending = build_answer({"position": 2, "question": "Q"})
    radar, _ = aggregate_criteria((*_answers(evaluation()), pending))
    assert radar is not None and all(p.answers == 1 for p in radar.points)


@pytest.mark.parametrize("count", [3, 5, 8, 12])
def test_radar_supports_any_number_of_axes(count):
    keys = [f"criterion_{i}" for i in range(count)]
    radar, _ = aggregate_criteria(_answers(evaluation(keys, [5] * count)))
    assert radar is not None and len(radar.points) == count
    drawing = radar_drawing(radar)
    assert drawing.width > 0 and drawing.height > 0


def test_radar_not_drawn_for_fewer_than_three_criteria():
    radar, reason = aggregate_criteria(_answers(evaluation(TK[:2], (5, 5))))
    assert radar is None and "at least 3" in reason
    assert "at least 3" in text(make_pdf(report([answer(ev=evaluation(TK[:2], (5, 5)))])))


def test_radar_not_drawn_when_scales_differ_or_missing():
    mixed, reason = aggregate_criteria(_answers(evaluation(scale=(0, 10)), evaluation(scores=(4, 3, 2, 1), scale=(0, 5))))
    assert mixed is None and "different scales" in reason
    ev = evaluation()
    del ev["evaluation_details"]["score_scale"]
    none_scale, reason = aggregate_criteria(_answers(ev))
    assert none_scale is None and "scale" in reason


def test_radar_not_drawn_without_data():
    assert aggregate_criteria(())[0] is None
    assert aggregate_criteria(_answers({"overall_score": 50}))[0] is None


def test_radar_labels_and_scale_are_in_the_pdf():
    t = text(make_pdf())
    assert "Criteria radar chart" in t and "scale 0-10" in t and "No values are estimated" in t
    for label in ("Technical accuracy", "Results and impact"):
        assert label.split()[0] in t


# ------------------------------------------------------------------ privacy
def test_no_candidate_text_in_logs(caplog):
    caplog.set_level("DEBUG")
    secret = "SECRET-TRANSCRIPT-TEXT-12345"
    make_pdf(report([answer(transcript=secret, ev=evaluation())], candidate_name="Zed Secretname"))
    assert secret not in caplog.text and "Zed Secretname" not in caplog.text


def test_repr_of_data_hides_candidate_speech_and_name():
    data = report([answer(transcript="PRIVATE-WORDS", ev=evaluation())])
    assert "PRIVATE-WORDS" not in repr(data) and "Asha" not in repr(data)


def test_no_files_are_written_while_rendering(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_pdf()
    assert list(tmp_path.iterdir()) == []


def test_email_is_not_part_of_the_report_data():
    import dataclasses
    from app.services.reporting.data import ReportData
    assert "email" not in {f.name for f in dataclasses.fields(ReportData)}
