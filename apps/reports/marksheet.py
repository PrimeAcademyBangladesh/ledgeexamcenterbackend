"""
PDF marksheet renderer for ExamResult — used by /reports/{id}/marksheet/.

Layout (portrait A4):
  - Teal header: "LEAD EDGE LTD" / "MARKSHEET" left | logo right
  - Gold accent rule
  - Candidate info card (Name, ULN, Qualification, Date in DD/MM/YYYY)
  - Examination Details block
  - Score + grade tile
  - PASSED / DID NOT PASS result line
  - Teal footer band

Logo is loaded from the frontend assets (lead-edge-logo.webp) via Pillow, which
converts it to PNG in memory so reportlab can render it. Falls back gracefully if
the file is missing.
"""
from __future__ import annotations

import io
import os

from django.conf import settings
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# ── Brand palette ─────────────────────────────────────────────────
TEAL        = HexColor("#1A4D58")
TEAL_LIGHT  = HexColor("#b0d8e0")
GOLD        = HexColor("#B8943C")
LIGHT_BG    = HexColor("#F4F4F4")
LIGHT_LABEL = HexColor("#6B7280")
DARK_TEXT   = HexColor("#0F172A")
PASS_GREEN  = HexColor("#1F8A4C")
FAIL_RED    = HexColor("#C03A3A")

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm


# ── Logo loader ───────────────────────────────────────────────────
def _logo_reader() -> ImageReader | None:
    """
    Return a reportlab ImageReader for the company logo, or None.
    Looks only inside the backend's own static/marksheet/logo.png.
    """
    logo_path = os.path.join(settings.BASE_DIR, "static", "marksheet", "logo.png")
    if os.path.exists(logo_path):
        try:
            return ImageReader(logo_path)
        except Exception:
            pass
    return None


# ── Public API ────────────────────────────────────────────────────
def render_marksheet(result) -> bytes:
    """Render an ExamResult as a PDF and return the raw bytes."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Marksheet — {result.learner.first_name} {result.learner.last_name}")
    c.setAuthor("Lead Edge Ltd")

    _draw_header(c)
    _draw_gold_rule(c, y=PAGE_H - 47 * mm)
    y = _draw_candidate_block(c, result, top=PAGE_H - 55 * mm)
    y = _draw_examination_block(c, result, top=y - 8 * mm)
    y = _draw_score_tile(c, result, top=y - 8 * mm)
    _draw_result_line(c, result, y=y - 18 * mm)
    _draw_footer(c)

    c.showPage()
    c.save()
    return buf.getvalue()


# ── Section renderers ─────────────────────────────────────────────
def _draw_header(c: canvas.Canvas) -> None:
    band_h = 40 * mm
    c.setFillColor(TEAL)
    c.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)

    # Left: company name → MARKSHEET stacked
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(MARGIN, PAGE_H - band_h + 26 * mm, "LEAD EDGE LTD")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, PAGE_H - band_h + 18 * mm, "MARKSHEET")

    # Right: logo
    logo = _logo_reader()
    if logo:
        try:
            logo_h = 28 * mm
            logo_w = 50 * mm
            logo_x = PAGE_W - MARGIN - logo_w
            logo_y = PAGE_H - band_h + (band_h - logo_h) / 2
            c.drawImage(logo, logo_x, logo_y,
                        width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask="auto")
        except Exception:
            pass


def _draw_gold_rule(c: canvas.Canvas, y: float) -> None:
    c.setFillColor(GOLD)
    c.rect(0, y, PAGE_W, 2.5 * mm, fill=1, stroke=0)


def _draw_candidate_block(c: canvas.Canvas, result, top: float) -> float:
    learner = result.learner
    full_name = f"{learner.first_name} {learner.last_name}".strip()
    profile = getattr(learner, "learner_profile", None)
    uln = profile.uln if profile and profile.uln else "—"

    # UK date format: DD/MM/YYYY
    date_str = (
        result.exam_date.strftime("%d/%m/%Y")
        if result.exam_date else "—"
    )

    col_w = (PAGE_W - 2 * MARGIN) / 2
    left_x  = MARGIN + 8 * mm
    right_x = MARGIN + col_w + 4 * mm
    # Cap the short fixed-format fields' width so they ellipsise instead of
    # overrunning into the neighbouring column. The qualification title can
    # run much longer, so it wraps onto extra lines instead (see _wrap_text);
    # the card grows to fit however many lines that produces.
    col_max_w = col_w - 10 * mm
    value_font, value_size, line_gap = "Helvetica-Bold", 11, 4.6 * mm

    qualification_lines = _wrap_text(c, result.qualification.title, value_font, value_size, col_max_w)
    h = 36 * mm + (len(qualification_lines) - 1) * line_gap

    c.setFillColor(LIGHT_BG)
    c.roundRect(MARGIN, top - h, PAGE_W - 2 * MARGIN, h, 2 * mm, fill=1, stroke=0)

    _label_value(c, left_x,  top - 9 * mm,  "CANDIDATE NAME", full_name, max_width=col_max_w)
    _label_value(c, right_x, top - 9 * mm,  "ULN",            str(uln), max_width=col_max_w)
    _label_lines(c, left_x,  top - 22 * mm, "QUALIFICATION",  qualification_lines, line_gap=line_gap)
    _label_value(c, right_x, top - 22 * mm, "DATE",           date_str, max_width=col_max_w)

    return top - h


def _draw_examination_block(c: canvas.Canvas, result, top: float) -> float:
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, top - 5 * mm, "Examination Details")
    c.setFillColor(GOLD)
    c.rect(MARGIN, top - 6.5 * mm, 30 * mm, 0.6 * mm, fill=1, stroke=0)

    m, s = divmod(result.time_taken_seconds or 0, 60)
    time_str = f"{m}m {s}s"

    col_w  = (PAGE_W - 2 * MARGIN) / 2
    left_x  = MARGIN
    right_x = MARGIN + col_w

    _label_value(c, left_x,  top - 16 * mm, "EXAM TITLE",  result.exam_config.title)
    _label_value(c, right_x, top - 16 * mm, "INVIGILATOR", result.invigilator_name or "—")
    _label_value(c, left_x,  top - 28 * mm, "TIME TAKEN",  time_str)

    return top - 32 * mm


def _draw_score_tile(c: canvas.Canvas, result, top: float) -> float:
    tile_h = 36 * mm
    tile_y = top - tile_h
    c.setFillColor(TEAL)
    c.roundRect(MARGIN, tile_y, PAGE_W - 2 * MARGIN, tile_h, 2 * mm, fill=1, stroke=0)

    # Left half: score percentage
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(MARGIN + 35 * mm, tile_y + 18 * mm, f"{result.score_percent}%")
    c.setFont("Helvetica", 9)
    c.drawCentredString(MARGIN + 35 * mm - 6, tile_y + 10 * mm, "SCORE")

    # Right half: gold grade pill
    pill_w = 70 * mm
    pill_h = 22 * mm
    pill_x = PAGE_W - MARGIN - pill_w - 10 * mm
    pill_y = tile_y + (tile_h - pill_h) / 2
    c.setFillColor(GOLD)
    c.roundRect(pill_x, pill_y, pill_w, pill_h, 2 * mm, fill=1, stroke=0)
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 16)
    grade_label = (result.grade or "").upper().replace("_", " ")
    c.drawCentredString(pill_x + pill_w / 2, pill_y + 7 * mm + 5, grade_label)

    return tile_y


def _draw_result_line(c: canvas.Canvas, result, y: float) -> None:
    label = "RESULT: PASSED" if result.passed else "RESULT: DID NOT PASS"
    c.setFillColor(PASS_GREEN if result.passed else FAIL_RED)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(PAGE_W / 2, y, label)


def _draw_footer(c: canvas.Canvas) -> None:
    band_h = 18 * mm
    c.setFillColor(TEAL)
    c.rect(0, 0, PAGE_W, band_h, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 8)
    c.drawCentredString(PAGE_W / 2, 11 * mm, "Lead Edge Ltd — Registered in England & Wales")
    c.drawCentredString(PAGE_W / 2, 6 * mm,
                        "This document is generated electronically and does not require a signature.")


# ── Helpers ───────────────────────────────────────────────────────
def _ellipsise(c: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float) -> str:
    """Shorten `text` with a trailing "…" until it fits within `max_width`."""
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text
    ellipsis = "…"
    while text and c.stringWidth(text + ellipsis, font_name, font_size) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _label_value(c: canvas.Canvas, x: float, y: float, label: str, value: str,
                 max_width: float | None = None) -> None:
    c.setFillColor(LIGHT_LABEL)
    c.setFont("Helvetica", 7.5)
    c.drawString(x, y, label)
    c.setFillColor(DARK_TEXT)
    value_font, value_size = "Helvetica-Bold", 11
    c.setFont(value_font, value_size)
    if max_width is not None:
        value = _ellipsise(c, value, value_font, value_size, max_width)
    c.drawString(x, y - 5 * mm, value)


def _wrap_text(c: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    """Greedy word-wrap: split `text` into lines that each fit `max_width`."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or c.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _label_lines(c: canvas.Canvas, x: float, y: float, label: str, lines: list[str],
                 line_gap: float) -> None:
    """Like `_label_value`, but draws a pre-wrapped multi-line value."""
    c.setFillColor(LIGHT_LABEL)
    c.setFont("Helvetica", 7.5)
    c.drawString(x, y, label)
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 11)
    for i, line in enumerate(lines):
        c.drawString(x, y - 5 * mm - i * line_gap, line)
