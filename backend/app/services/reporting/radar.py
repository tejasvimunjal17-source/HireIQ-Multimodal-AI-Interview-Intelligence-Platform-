"""Radar chart of rubric criteria (Day 6), drawn with ReportLab graphics only (no matplotlib, no images).

Honest-chart rules
- Only STORED criterion scores are plotted: each axis is the plain mean, over the evaluated answers that have that
  criterion, of the stored score. Nothing is estimated or filled in.
- The axis range is the rubric score scale stored with the evaluation (e.g. 0-10); the centre is the scale minimum.
- Fewer than 3 criteria, no scale, or answers scored on different scales: NO chart (a reason is returned instead),
  because a 1- or 2-axis "radar" is misleading.
- Any number of criteria >= 3 is supported; long labels are wrapped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from reportlab.graphics.shapes import Drawing, Line, Polygon, String
from reportlab.lib import colors

from app.services.reporting.data import AnswerData

MIN_AXES = 3
MAX_AXES = 16


@dataclass(frozen=True)
class RadarPoint:
    key: str
    value: float
    answers: int  # how many evaluated answers contributed


@dataclass(frozen=True)
class RadarInput:
    points: tuple[RadarPoint, ...]
    scale: tuple[int, int]
    answers_total: int


def humanize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def aggregate_criteria(answers: tuple[AnswerData, ...]) -> tuple[RadarInput | None, str]:
    """-> (RadarInput, "") or (None, reason the chart is not shown)."""
    usable = [a for a in answers if a.is_evaluated and a.criteria]
    if not usable:
        return None, "No criterion scores are available for this session."
    scales = {a.scale for a in usable}
    if None in scales:
        return None, "The score scale was not stored with the evaluation, so the chart axis cannot be set honestly."
    if len(scales) > 1:
        return None, "The answers were scored on different scales, so their criteria cannot share one chart."
    scale = next(iter(scales))
    sums: dict[str, list[float]] = {}
    for answer in usable:
        for criterion in answer.criteria:
            sums.setdefault(criterion.key, []).append(criterion.score)
    if len(sums) < MIN_AXES:
        return None, f"A radar chart needs at least {MIN_AXES} scored criteria; only {len(sums)} available."
    points = tuple(RadarPoint(k, math.fsum(v) / len(v), len(v)) for k, v in sorted(sums.items())[:MAX_AXES])
    return RadarInput(points=points, scale=scale, answers_total=len(usable)), ""


def _wrap(label: str, width: int = 16) -> list[str]:
    lines, current = [], ""
    for word in label.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return [line if len(line) <= width + 6 else line[: width + 3] + "..." for line in lines[:3]] or [label[:width]]


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def radar_drawing(
    data: RadarInput, *, width: float = 440, height: float = 330, font: str = "Helvetica", font_bold: str = "Helvetica-Bold",
    accent=colors.HexColor("#0E7490"),
) -> Drawing:
    low, high = data.scale
    n = len(data.points)
    cx, cy = width / 2, height / 2 - 4
    radius = min(width / 2 - 92, height / 2 - 46)
    drawing = Drawing(width, height)

    def at(index: int, fraction: float) -> tuple[float, float]:
        angle = math.pi / 2 - 2 * math.pi * index / n  # first axis at the top, clockwise
        return cx + radius * fraction * math.cos(angle), cy + radius * fraction * math.sin(angle)

    grid = colors.HexColor("#D5DCE6")
    for level in (0.2, 0.4, 0.6, 0.8, 1.0):  # rings
        ring = [c for i in range(n) for c in at(i, level)]
        drawing.add(Polygon(ring, strokeColor=grid, strokeWidth=0.6, fillColor=None))
    for i in range(n):  # spokes
        x, y = at(i, 1.0)
        drawing.add(Line(cx, cy, x, y, strokeColor=grid, strokeWidth=0.6))
    for level in (0.0, 0.5, 1.0):  # scale labels along the first spoke
        x, y = at(0, level)
        drawing.add(String(x - 4, y - 2.5, _fmt(low + (high - low) * level), fontName=font, fontSize=6.5, textAnchor="end",
                           fillColor=colors.HexColor("#6B7280")))

    shape = [c for i, p in enumerate(data.points) for c in at(i, (p.value - low) / (high - low))]
    drawing.add(Polygon(shape, strokeColor=accent, strokeWidth=1.6, fillColor=accent, fillOpacity=0.22))

    for i, p in enumerate(data.points):
        fraction = (p.value - low) / (high - low)
        px, py = at(i, fraction)
        drawing.add(Polygon([px - 2.4, py - 2.4, px + 2.4, py - 2.4, px + 2.4, py + 2.4, px - 2.4, py + 2.4],
                            fillColor=accent, strokeColor=colors.white, strokeWidth=0.6))
        angle = math.pi / 2 - 2 * math.pi * i / n
        cos, sin = math.cos(angle), math.sin(angle)
        lx, ly = cx + (radius + 14) * cos, cy + (radius + 14) * sin
        anchor = "middle" if abs(cos) < 0.3 else ("start" if cos > 0 else "end")
        lines = _wrap(humanize(p.key))
        label_y = ly + (4 + (len(lines) - 1) * 8 if sin > 0.3 else -9 if sin < -0.3 else 3 + (len(lines) - 1) * 4)
        for j, line in enumerate(lines):
            drawing.add(String(lx, label_y - j * 8, line, fontName=font_bold, fontSize=7.5, textAnchor=anchor,
                               fillColor=colors.HexColor("#1F2937")))
        value_anchor = "start" if cos >= 0 else "end"
        drawing.add(String(px + (5 if cos >= 0 else -5), py + 3, _fmt(p.value), fontName=font_bold, fontSize=7,
                           textAnchor=value_anchor, fillColor=accent))
    return drawing
