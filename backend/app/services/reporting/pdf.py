"""PDF rendering of the candidate evaluation report (Day 6), ReportLab only (no browser, no extra PDF library).

`render_report(data, generated_at)` is a pure function: it reads a ReportData and returns PDF bytes. It never
touches the database, never calls a model and never changes a stored value.

Safety
- Every piece of dynamic text (names, questions, transcripts, quotes, model output) goes through `Renderer.esc`:
  control characters removed, characters the embedded font cannot draw replaced by "?" (and counted in a visible
  note), then XML-escaped, so transcript text can never inject markup or break a Paragraph.
- Long text lives in splittable Paragraphs (never in table cells), and long unbroken words are split, so nothing is
  clipped or overflows the frame, however long the transcript.
- The embedded font is Bitstream Vera, which ships INSIDE the reportlab package (Latin, with accents). If it is
  missing the report falls back to Helvetica with Latin-1 only.
- Document metadata contains no candidate data. Nothing is logged here.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.pdfgen import canvas as pdfcanvas

from app.services.reporting.data import AnswerData, ReportData
from app.services.reporting.radar import aggregate_criteria, humanize, radar_drawing

REPORT_TITLE = "Candidate Interview Evaluation Report"
CONFIDENTIAL = (
    "CONFIDENTIAL - contains personal data and evaluation results of a candidate. For authorised hiring staff only. "
    "Do not forward, copy or store outside the hiring process."
)
NAVY, TEAL, INK, MUTED = (colors.HexColor(c) for c in ("#1B2A49", "#0E7490", "#1F2937", "#6B7280"))
PANEL, RULE = colors.HexColor("#F3F6FA"), colors.HexColor("#D5DCE6")
REC_STYLE = {  # (text colour, background); the WORD is always printed too, never colour alone
    "proceed": (colors.HexColor("#166534"), colors.HexColor("#DCFCE7"), "PROCEED"),
    "hold": (colors.HexColor("#92400E"), colors.HexColor("#FEF3C7"), "HOLD"),
    "reject": (colors.HexColor("#991B1B"), colors.HexColor("#FEE2E2"), "REJECT"),
}
PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 18 * mm, 24 * mm, 24 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‏  ‪-‮⁦-⁩﻿]")

# ---------------------------------------------------------------- fonts
_FONTS: dict[str, object] | None = None


def _fonts() -> dict[str, object]:
    """Register Bitstream Vera (shipped with reportlab) once. Returns names and the set of drawable code points."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    try:
        import reportlab

        folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
        files = {"HQ": "Vera.ttf", "HQ-Bold": "VeraBd.ttf", "HQ-Italic": "VeraIt.ttf", "HQ-BoldItalic": "VeraBI.ttf"}
        fonts = {name: TTFont(name, os.path.join(folder, file)) for name, file in files.items()}
        for font in fonts.values():
            pdfmetrics.registerFont(font)
        pdfmetrics.registerFontFamily("HQ", normal="HQ", bold="HQ-Bold", italic="HQ-Italic", boldItalic="HQ-BoldItalic")
        _FONTS = {"regular": "HQ", "bold": "HQ-Bold", "italic": "HQ-Italic", "glyphs": set(fonts["HQ"].face.charToGlyph)}
    except Exception:  # noqa: BLE001 - fall back to the built-in Latin-1 fonts
        _FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique", "glyphs": set(range(32, 256))}
    return _FONTS


def format_score(value: float) -> str:
    """The stored value exactly, up to 2 decimals (75.5 -> '75.5', 72.0 -> '72')."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _stamp(moment: datetime | None) -> str:
    if moment is None:
        return "Not recorded"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


class _NumberedCanvas(pdfcanvas.Canvas):
    """Two-pass canvas so every footer can say 'Page X of Y'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total: int) -> None:
        fonts = _fonts()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(MARGIN_X, 17 * mm, PAGE_W - MARGIN_X, 17 * mm)
        self.setFillColor(MUTED)
        self.setFont(fonts["regular"], 6.6)
        words, line, lines = CONFIDENTIAL.split(), "", []
        for word in words:
            if self.stringWidth(f"{line} {word}".strip(), fonts["regular"], 6.6) > CONTENT_W - 70:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        for i, text in enumerate(lines[:2]):
            self.drawString(MARGIN_X, 13 * mm - i * 8, text)
        self.setFont(fonts["bold"], 7.5)
        self.drawRightString(PAGE_W - MARGIN_X, 13 * mm, f"Page {self._pageNumber} of {total}")
        self.setFont(fonts["regular"], 6.6)
        self.drawRightString(PAGE_W - MARGIN_X, 13 * mm - 8, f"HireIQ - {REPORT_TITLE}")


class Renderer:
    def __init__(self, data: ReportData, generated_at: datetime) -> None:
        self.data, self.generated_at = data, generated_at
        fonts = _fonts()
        self.glyphs: set[int] = fonts["glyphs"]  # type: ignore[assignment]
        self.f, self.fb, self.fi = fonts["regular"], fonts["bold"], fonts["italic"]
        self.replaced = 0
        self.s = self._styles()

    # ------------------------------------------------------------ text safety
    def clean(self, text: object) -> str:
        if not isinstance(text, str):
            return ""
        out = []
        for ch in _CONTROL.sub("", text.replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n")):
            if ch == "\n" or ord(ch) in self.glyphs:
                out.append(ch)
            else:
                out.append("?")
                self.replaced += 1
        return "".join(out)

    def esc(self, text: object) -> str:
        return escape(self.clean(text)).replace("\n", "<br/>")

    def p(self, text: object, style: str = "body") -> Paragraph:
        return Paragraph(self.esc(text), self.s[style])

    # ------------------------------------------------------------ styles
    def _styles(self) -> dict[str, ParagraphStyle]:
        def make(name, font=None, size=9.2, lead=None, color=INK, alignment=TA_LEFT, **kw):
            return ParagraphStyle(name, fontName=font or self.f, fontSize=size, leading=lead or size * 1.38, textColor=color,
                                  alignment=alignment, splitLongWords=1, **kw)

        return {
            "body": make("body", spaceAfter=3),
            "small": make("small", size=7.8, color=MUTED, spaceAfter=2),
            "muted": make("muted", color=MUTED),
            "h1": make("h1", self.fb, 13.5, 17, NAVY, spaceBefore=10, spaceAfter=5, keepWithNext=1),
            "h2": make("h2", self.fb, 10.6, 14, NAVY, spaceBefore=7, spaceAfter=3, keepWithNext=1),
            "h3": make("h3", self.fb, 9.2, 12, TEAL, spaceBefore=5, spaceAfter=2),
            "label": make("label", self.fb, 8, color=MUTED),
            "cell": make("cell", size=8.8),
            "cellb": make("cellb", self.fb, 8.8),
            "quote": make("quote", self.fi, 8.6, color=colors.HexColor("#374151"), leftIndent=10, spaceAfter=2),
            "transcript": make("transcript", size=8.6, color=colors.HexColor("#111827"), backColor=PANEL, borderPadding=(5, 6, 5, 6),
                               leftIndent=6, rightIndent=6, spaceBefore=6, spaceAfter=8),
            "expl": make("expl", size=8.6, leftIndent=6, spaceAfter=2),
            "bullet": make("bullet", leftIndent=11, bulletIndent=2, spaceAfter=1.5),
            "banner": make("banner", self.fb, 8.8, color=colors.HexColor("#92400E")),
            "bannerbody": make("bannerbody", size=8.4, color=colors.HexColor("#92400E")),
            "big": make("big", self.fb, 25, 28, NAVY),
            "bigunit": make("bigunit", size=9, color=MUTED),
            "white": make("white", self.fb, 17, 21, colors.white),
            "whitesmall": make("whitesmall", size=8.6, lead=12, color=colors.HexColor("#CBD5E1")),
            "whiteright": make("whiteright", size=8.4, lead=12, color=colors.HexColor("#CBD5E1"), alignment=2),
        }

    # ------------------------------------------------------------ small building blocks
    def bar(self, value: float, low: float, high: float, width: float = 110, height: float = 7) -> Drawing:
        drawing = Drawing(width, height + 2)
        drawing.add(Rect(0, 1, width, height, fillColor=colors.HexColor("#E5E9F0"), strokeColor=None))
        share = 0.0 if high <= low else max(0.0, min(1.0, (value - low) / (high - low)))
        if share > 0:
            drawing.add(Rect(0, 1, width * share, height, fillColor=TEAL, strokeColor=None))
        return drawing

    def chip(self, rec: str | None, width: float = 62) -> Table:
        text, bg, word = REC_STYLE.get(rec or "", (MUTED, PANEL, "NOT RECORDED"))
        style = ParagraphStyle("chip", fontName=self.fb, fontSize=8.2, leading=10, textColor=text, alignment=1)
        table = Table([[Paragraph(word, style)]], colWidths=[width + (44 if rec is None else 0)])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.8, text),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return table

    def kv(self, rows: list[tuple[str, str]]) -> Table:
        table = Table([[Paragraph(self.esc(k), self.s["label"]), self.p(v, "cell")] for k, v in rows],
                      colWidths=[CONTENT_W * 0.27, CONTENT_W * 0.73])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
        return table

    def bullets(self, items: tuple[str, ...] | list[str]) -> list[Paragraph]:
        return [Paragraph(self.esc(i), self.s["bullet"], bulletText="•") for i in items]

    # ------------------------------------------------------------ sections
    def header(self) -> list:
        d = self.data
        left = [Paragraph("HireIQ", self.s["white"]), Paragraph("AI interview intelligence", self.s["whitesmall"]),
                Spacer(1, 6), Paragraph(REPORT_TITLE, ParagraphStyle("t", parent=self.s["white"], fontSize=12.5, leading=16))]
        right = [Paragraph(f"Generated<br/>{self.esc(_stamp(self.generated_at))}", self.s["whiteright"])]
        if d.interview_title:
            left.append(Paragraph(self.esc(d.interview_title), self.s["whitesmall"]))
        table = Table([[left, right]], colWidths=[CONTENT_W * 0.7, CONTENT_W * 0.3])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                                   ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                                   ("LINEBELOW", (0, 0), (-1, -1), 3, TEAL)]))
        return [table, Spacer(1, 8)]

    def candidate_info(self) -> list:
        d = self.data
        evaluated = len(d.evaluated)
        rows = [
            ("Candidate name", d.candidate_name or "Not provided"),
            ("Candidate ID", d.candidate_id or "Not available"),
            ("Interview", d.interview_title or "Not available"),
            ("Interview session ID", d.session_id),
            ("Interview date", _stamp(d.interview_date)),
            ("Interview status", humanize(d.session_status)),
            ("Answers evaluated", f"{evaluated} of {len(d.answers)}"),
        ]
        return [self.p("Candidate information", "h1"), self.kv(rows), Spacer(1, 6)]

    def incomplete_banner(self) -> list:
        d = self.data
        pending = [a for a in d.answers if not a.is_evaluated and not (a.no_speech and a.evaluation_error in (None, "no_speech"))]
        silent = [a for a in d.answers if not a.is_evaluated and a not in pending]
        if d.is_complete and not any(a.issues for a in d.answers):
            return []
        lines = []
        if not d.is_complete:
            lines.append("PARTIAL REPORT - some answers have no evaluation yet. Scores below cover only the evaluated answers.")
            lines += [f"Question {a.position}: {a.status_text}" for a in pending]
        if silent:
            lines += [f"Question {a.position}: {a.status_text}" for a in silent]
        lines += [f"Question {a.position}: {issue}" for a in d.answers for issue in a.issues]
        body = [Paragraph(self.esc(lines[0]), self.s["banner"])] + [Paragraph(self.esc(t), self.s["bannerbody"]) for t in lines[1:]]
        table = Table([[body]], colWidths=[CONTENT_W])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
                                   ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#B45309")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        return [table, Spacer(1, 6)]

    def _score_label(self) -> tuple[float | None, str]:
        d = self.data
        if d.stored_overall_score is not None:
            return d.stored_overall_score, "Stored session score"
        avg = d.average_score
        if avg is None:
            return None, ""
        n = len(d.evaluated)
        return avg, f"Average of {n} evaluated answer{'s' if n != 1 else ''}"

    def _tally(self) -> str:
        counts = {r: sum(1 for a in self.data.evaluated if a.recommendation == r) for r in REC_STYLE}
        parts = [f"{REC_STYLE[r][2].capitalize()} {n}" for r, n in counts.items() if n]
        return ", ".join(parts) if parts else "none recorded"

    def executive_summary(self) -> list:
        d = self.data
        score, label = self._score_label()
        score_cell = [Paragraph("OVERALL SCORE", self.s["label"])]
        if score is None:
            score_cell += [Paragraph("Not available", self.s["cellb"]), Paragraph("No answer has been evaluated yet.", self.s["small"])]
        else:
            score_cell += [Paragraph(f"{format_score(score)} <font size='10' color='#6B7280'>/ 100</font>", self.s["big"]),
                           Paragraph(self.esc(label), self.s["small"])]
        rec_cell = [Paragraph("HIRING RECOMMENDATION (ADVISORY)", self.s["label"]), Spacer(1, 3), self.chip(d.stored_recommendation)]
        if d.stored_recommendation:
            rec_cell.append(Paragraph("Stored session recommendation.", self.s["small"]))
        else:
            rec_cell.append(Paragraph(self.esc(f"No session-level recommendation is stored. Per-answer advice: {self._tally()}."), self.s["small"]))
        table = Table([[score_cell, rec_cell]], colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.58])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, RULE),
                                   ("LINEAFTER", (0, 0), (0, 0), 0.6, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
        story = [self.p("Executive summary", "h1"), table, Spacer(1, 4)]
        evaluated = d.evaluated
        if evaluated:
            story.append(self.p("Evaluation summary", "h2"))
            for a in evaluated:
                if a.summary:
                    story.append(Paragraph(f"<b>Question {a.position}.</b> {self.esc(a.summary)}", self.s["body"]))
            for title, picked in (("Key strengths", self._unique([s for a in evaluated for s in a.strengths])),
                                  ("Areas for improvement", self._unique([s for a in evaluated for s in a.improvements]))):
                if picked:
                    story += [self.p(title, "h2"), *self.bullets(picked)]
            story.append(self.p("Summaries, strengths and improvement points are taken unchanged from the stored per-answer evaluations.", "small"))
        return story

    @staticmethod
    def _unique(items: list[str], limit: int = 6) -> list[str]:
        seen, out = set(), []
        for item in items:
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out[:limit]

    def score_summary(self) -> list:
        d = self.data
        story = [CondPageBreak(150), self.p("Score summary", "h1")]
        score, label = self._score_label()
        if score is None:
            return story + [self.p("No evaluated answers: there is no score to show.", "muted")]
        story += [self.bar(score, 0, 100, width=CONTENT_W, height=11),
                  Paragraph(f"{self.esc(label)}: <b>{format_score(score)}</b> on a 0-100 scale (stored values are shown unchanged).", self.s["small"]),
                  Spacer(1, 4)]
        head = [Paragraph(h, self.s["label"]) for h in ("QUESTION", "ANSWER SCORE (0-100)", "ADVICE")]
        rows = [head]
        for a in d.answers:
            excerpt = a.question if len(a.question) <= 70 else a.question[:67] + "..."
            if a.is_evaluated:
                rows.append([self.p(f"{a.position}. {excerpt}", "cell"), Paragraph(f"<b>{format_score(a.overall_score)}</b>", self.s["cell"]),
                             self.p(REC_STYLE[a.recommendation][2].capitalize() if a.recommendation else "Not recorded", "cell")])
            else:
                rows.append([self.p(f"{a.position}. {excerpt}", "cell"), self.p("Not scored", "muted"), self.p(a.status_text, "small")])
        table = Table(rows, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.2, CONTENT_W * 0.3], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PANEL), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return story + [table]

    def radar_section(self) -> list:
        story = [CondPageBreak(340), self.p("Criteria radar chart", "h1")]
        data, reason = aggregate_criteria(self.data.answers)
        if data is None:
            return story + [self.p(f"Chart not shown. {reason}", "muted")]
        low, high = data.scale
        chart = radar_drawing(data, font=self.f, font_bold=self.fb)
        chart.hAlign = "CENTER"
        caption = (f"Each axis is the mean stored criterion score over the evaluated answers that include that criterion "
                   f"(scale {low}-{high}; centre = {low}). {len(data.points)} criteria, {data.answers_total} evaluated "
                   f"answer{'s' if data.answers_total != 1 else ''}. No values are estimated.")
        partial = [f"{humanize(p.key)} ({p.answers} of {data.answers_total} answers)" for p in data.points if p.answers < data.answers_total]
        story += [KeepTogether([chart, Paragraph(self.esc(caption), self.s["small"])])]
        if partial:
            story.append(self.p("Criteria present in only some answers: " + "; ".join(partial) + ".", "small"))
        return story

    def question_sections(self) -> list:
        story = [CondPageBreak(170), self.p("Per-question evaluation", "h1")]
        if not self.data.answers:
            return story + [self.p("This session has no recorded answers.", "muted")]
        for a in self.data.answers:
            story.append(CondPageBreak(130))
            story += self._question(a)
        return story

    def _question(self, a: AnswerData) -> list:
        story: list = [self.p(f"Question {a.position}", "h2"), self.p(a.question, "body")]
        if a.is_evaluated:
            low, high = a.scale if a.scale else (None, None)
            head = Table([[Paragraph(f"<b>{format_score(a.overall_score)}</b> / 100", ParagraphStyle("qs", parent=self.s["cell"], fontSize=11, leading=14)),
                           Paragraph("Answer score (stored)", self.s["small"]), self.chip(a.recommendation)]],
                         colWidths=[CONTENT_W * 0.25, CONTENT_W * 0.45, CONTENT_W * 0.3])
            head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                      ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("ALIGN", (2, 0), (2, 0), "RIGHT")]))
            story.append(head)
            if a.summary:
                story += [Spacer(1, 3), self.p(a.summary, "body")]
            if a.criteria:
                story += [CondPageBreak(70), self.p("Criterion scores", "h3")]
                for c in a.criteria:
                    scale_txt = f" / {high}" if high is not None else ""
                    row = Table([[Paragraph(self.esc(humanize(c.key)), self.s["cellb"]),
                                  self.bar(c.score, low, high, 90) if low is not None else "",
                                  Paragraph(f"<b>{format_score(c.score)}</b>{scale_txt}", self.s["cell"]),
                                  Paragraph(f"weight {format_score(c.weight)}" if c.weight is not None else "", self.s["small"])]],
                                colWidths=[CONTENT_W * 0.38, CONTENT_W * 0.22, CONTENT_W * 0.15, CONTENT_W * 0.25])
                    row.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                             ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
                    story.append(KeepTogether([row, *( [self.p(c.explanation, "expl")] if c.explanation else [] )]))
                    for quote in c.evidence_quotes:
                        story.append(Paragraph(f"“{self.esc(quote)}”", self.s["quote"]))
        else:
            story.append(self.p(f"Not scored: {a.status_text}.", "muted"))
        story += [CondPageBreak(70), self.p("Candidate transcript (automatic speech recognition)", "h3")]
        if a.transcript and a.transcript.strip():
            story.append(Paragraph(self.esc(a.transcript.strip()), self.s["transcript"]))
        elif a.no_speech:
            story.append(self.p("No speech was detected in this recording.", "muted"))
        else:
            story.append(self.p("No transcript is available for this answer.", "muted"))
        return story

    def nlp_section(self) -> list:
        story = [CondPageBreak(140), self.p("NLP insights (advisory)", "h1")]
        with_nlp = [a for a in self.data.evaluated if a.nlp]
        if not with_nlp:
            return story + [self.p("NLP insights are unavailable for this report (not generated or not stored).", "muted")]
        story.append(self.p("Context for a human reviewer only. Keywords, entities, sentiment and the confidence indicator are automatic text "
                            "analyses: they are NOT validated measures of competence, personality or honesty, and they did not influence any "
                            "score or recommendation in this report.", "small"))
        for a in with_nlp:
            n = a.nlp or {}
            story.append(CondPageBreak(90))
            story.append(self.p(f"Question {a.position}", "h2"))
            if n.get("keywords"):
                story.append(Paragraph("<b>Keywords:</b> " + self.esc(", ".join(k["text"] for k in n["keywords"])), self.s["body"]))
            if n.get("entities"):
                story.append(Paragraph("<b>Detected entities:</b> " + self.esc("; ".join(f"{e['text']} ({e['label']})" for e in n["entities"])), self.s["body"]))
                story.append(self.p("Entities are names the text analysis found; they are not evidence of skill.", "small"))
            s = n.get("sentiment")
            if s:
                story.append(Paragraph(f"<b>Sentiment (VADER):</b> {self.esc(s['label'])} - positive {s['positive']:.2f}, neutral {s['neutral']:.2f}, "
                                       f"negative {s['negative']:.2f}, compound {s['compound']:+.2f}.", self.s["body"]))
                story.append(self.p("Tone of the wording only. Technical answers are mostly neutral; a calm tone is not a weaker answer.", "small"))
            c = n.get("confidence")
            if c:
                story.append(Paragraph(f"<b>Confidence indicator (EXPERIMENTAL heuristic):</b> {self.esc(c['label'])} ({c['score']:.2f} on 0-1).", self.s["body"]))
                rows = [[Paragraph(h, self.s["label"]) for h in ("SIGNAL", "VALUE", "LIMITATION")]]
                for i in c["indicators"]:
                    rows.append([self.p(humanize(i["name"]), "cell"), Paragraph(f"{i['value']:.2f}", self.s["cell"]), self.p(i["limitation"], "small")])
                t = Table(rows, colWidths=[CONTENT_W * 0.24, CONTENT_W * 0.1, CONTENT_W * 0.66], repeatRows=1)
                t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PANEL), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story += [t, self.p("Rule-based text-pattern signal. It is not a measure of a person's confidence, personality, honesty or competence and does not affect the recommendation.", "small")]
            if not (n.get("keywords") or n.get("entities") or s or c):
                story.append(self.p("No NLP results were stored for this answer.", "muted"))
        return story

    def recommendation_section(self) -> list:
        d = self.data
        story = [CondPageBreak(150), self.p("Recommendation", "h1")]
        if d.stored_recommendation:
            story += [self.chip(d.stored_recommendation), Spacer(1, 4)]
        elif d.evaluated:
            story.append(self.p("No session-level recommendation is stored. The stored per-answer advice is listed below; this report does not combine it into a new decision.", "body"))
        else:
            story.append(self.p("No recommendation is available because no answer has been evaluated.", "muted"))
        rows = [[Paragraph(h, self.s["label"]) for h in ("QUESTION", "STORED ADVICE")]]
        for a in d.evaluated:
            rows.append([self.p(f"Question {a.position}", "cell"), self.chip(a.recommendation, 62)])
        if len(rows) > 1:
            t = Table(rows, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5], hAlign="LEFT")
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PANEL), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            story.append(t)
        story += [Spacer(1, 4), self.p("The recommendation is the stored output of the automated, rubric-based evaluation. It is advice for the hiring "
                                       "manager, not a hiring decision; the final decision stays with people. Sentiment and the confidence indicator "
                                       "play no part in it.", "small")]
        if self.replaced:
            story.append(self.p(f"Note: {self.replaced} character(s) in the text could not be drawn with the report font and are shown as '?'.", "small"))
        return story

    # ------------------------------------------------------------ assemble
    def build(self) -> bytes:
        def later_pages(canvas, doc):
            canvas.saveState()
            canvas.setFont(self.f, 7)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN_X, PAGE_H - 14 * mm, f"HireIQ - {REPORT_TITLE}")
            canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 14 * mm, f"Session {self.data.session_id[:8]}")
            canvas.setStrokeColor(RULE)
            canvas.line(MARGIN_X, PAGE_H - 16 * mm, PAGE_W - MARGIN_X, PAGE_H - 16 * mm)
            canvas.restoreState()

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
            title=REPORT_TITLE, author="HireIQ", subject="Confidential candidate evaluation", creator="HireIQ", pageCompression=1,
        )
        # The first page has its own banner, so it needs less top margin than later pages.
        story: list = []
        story += self.header() + self.candidate_info() + self.incomplete_banner() + self.executive_summary()
        story += self.score_summary() + self.radar_section() + self.question_sections() + self.nlp_section()
        story += self.recommendation_section()
        doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=later_pages, canvasmaker=_NumberedCanvas)
        return buffer.getvalue()


def render_report(data: ReportData, generated_at: datetime | None = None) -> bytes:
    """ReportData -> PDF bytes. `generated_at` is injectable so the output is reproducible in tests."""
    return Renderer(data, generated_at or datetime.now(timezone.utc)).build()
