"""
PDF marksheet renderer for ExamResult — used by /reports/{id}/marksheet/.

Lays out a single A4 page with:
  - Teal header band: logo + "MARKSHEET" + "Est. 2009"
  - Gold accent line
  - Candidate info block
  - Examination details block
  - Score + grade tile
  - PASSED / DID NOT PASS line
  - Legal footer

The logo file is expected at  static/marksheet/logo.png  (resolved via
Django's staticfiles finders so it works both in dev and after collectstatic).
"""
from __future__ import annotations

import io
import os

from django.conf import settings
from django.contrib.staticfiles import finders
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


# ── Brand palette (matches screenshot) ───────────────────────────
TEAL        = HexColor("#1A4D58")
GOLD        = HexColor("#B8943C")
LIGHT_BG    = HexColor("#F4F4F4")
LIGHT_LABEL = HexColor("#6B7280")
DARK_TEXT   = HexColor("#0F172A")
PASS_GREEN  = HexColor("#1F8A4C")
FAIL_RED    = HexColor("#C03A3A")

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm


# ── Logo resolution ──────────────────────────────────────────────
def _logo_path() -> str | None:
    """
    Resolve the marksheet logo. Returns an absolute filesystem path
    or None if no logo is found (the header then falls back to text).
    """
    found = finders.find("marksheet/logo.png")
    if found:
        return found
    fallback = os.path.join(settings.BASE_DIR, "static", "marksheet", "logo.png")
    return fallback if os.path.exists(fallback) else None


# ── Public API ───────────────────────────────────────────────────
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


# ── Section renderers ────────────────────────────────────────────
def _draw_header(c: canvas.Canvas) -> None:
    band_h = 40 * mm
    c.setFillColor(TEAL)
    c.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)

    # Logo (left) — optional
    logo = _logo_path()
    if logo:
        try:
            # Logo: centered vertically against the two text lines on its right.
            # Text baselines sit at 22mm and 16mm above the band bottom, so the
            # visual midpoint is ~19mm — placing the logo at y=12mm with h=18mm
            # puts its center (21mm) close to that midpoint and keeps it inside
            # the band without extending past the body text.
            c.drawImage(
                logo,
                MARGIN, PAGE_H - band_h + 12 * mm,
                width=18 * mm, height=18 * mm,
                preserveAspectRatio=True, mask="auto",
            )
            text_x = MARGIN + 22 * mm
        except Exception:
            text_x = MARGIN
    else:
        text_x = MARGIN

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(text_x, PAGE_H - band_h + 22 * mm, "LEAD EDGE LTD")
    c.setFont("Helvetica", 9)
    c.drawString(text_x, PAGE_H - band_h + 16 * mm, "End-Point Assessment Organisation")

    # Right side
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - band_h + 22 * mm, "MARKSHEET")
    c.setFont("Helvetica", 9)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - band_h + 16 * mm, "Est. 2009")


def _draw_gold_rule(c: canvas.Canvas, y: float) -> None:
    c.setFillColor(GOLD)
    c.rect(0, y, PAGE_W, 2.5 * mm, fill=1, stroke=0)


def _draw_candidate_block(c: canvas.Canvas, result, top: float) -> float:
    # Box height chosen so the bottom padding (below the last value baseline)
    # matches the top padding (9mm above the first label). Last value sits at
    # top-27mm; bottom at top-36mm gives 9mm symmetric padding.
    h = 36 * mm
    c.setFillColor(LIGHT_BG)
    c.roundRect(MARGIN, top - h, PAGE_W - 2 * MARGIN, h, 2 * mm, fill=1, stroke=0)

    learner = result.learner
    full_name = f"{learner.first_name} {learner.last_name}".strip()
    profile = getattr(learner, "learner_profile", None)
    uln = profile.uln if profile and profile.uln else "—"

    col_w = (PAGE_W - 2 * MARGIN) / 2
    left_x = MARGIN + 8 * mm
    right_x = MARGIN + col_w + 4 * mm

    _label_value(c, left_x,  top - 9 * mm,  "CANDIDATE NAME", full_name)
    _label_value(c, right_x, top - 9 * mm,  "ULN",            str(uln))
    _label_value(c, left_x,  top - 22 * mm, "QUALIFICATION",  result.qualification.title)
    _label_value(c, right_x, top - 22 * mm, "DATE",           result.exam_date.isoformat())

    return top - h


def _draw_examination_block(c: canvas.Canvas, result, top: float) -> float:
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, top - 5 * mm, "Examination Details")
    # underline
    c.setFillColor(GOLD)
    c.rect(MARGIN, top - 6.5 * mm, 30 * mm, 0.6 * mm, fill=1, stroke=0)

    m, s = divmod(result.time_taken_seconds or 0, 60)
    time_str = f"{m}m {s}s"
    questions_str = f"{result.correct_count} / {result.total_questions} correct"

    col_w = (PAGE_W - 2 * MARGIN) / 2
    left_x = MARGIN
    right_x = MARGIN + col_w

    _label_value(c, left_x,  top - 16 * mm, "EXAM TITLE",  result.exam_config.title)
    _label_value(c, right_x, top - 16 * mm, "INVIGILATOR", result.invigilator_name or "—")
    _label_value(c, left_x,  top - 28 * mm, "TIME TAKEN", time_str)
    _label_value(c, right_x, top - 28 * mm, "QUESTIONS",  questions_str)

    return top - 32 * mm


def _draw_score_tile(c: canvas.Canvas, result, top: float) -> float:
    tile_h = 36 * mm
    tile_y = top - tile_h
    c.setFillColor(TEAL)
    c.roundRect(MARGIN, tile_y, PAGE_W - 2 * MARGIN, tile_h, 2 * mm, fill=1, stroke=0)

    # Left half: score
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(MARGIN + 35 * mm, tile_y + 18 * mm, f"{result.score_percent}%")
    c.setFont("Helvetica", 9)
    c.drawCentredString(MARGIN + 35 * mm, tile_y + 10 * mm, "SCORE")

    # Right half: gold pill with grade
    pill_w = 70 * mm
    pill_h = 22 * mm
    pill_x = PAGE_W - MARGIN - pill_w - 10 * mm
    pill_y = tile_y + (tile_h - pill_h) / 2
    c.setFillColor(GOLD)
    c.roundRect(pill_x, pill_y, pill_w, pill_h, 2 * mm, fill=1, stroke=0)
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 16)
    grade_label = (result.grade or "").upper().replace("_", " ")
    c.drawCentredString(pill_x + pill_w / 2, pill_y + 7 * mm, grade_label)

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


# ── Helpers ──────────────────────────────────────────────────────
def _label_value(c: canvas.Canvas, x: float, y: float, label: str, value: str) -> None:
    c.setFillColor(LIGHT_LABEL)
    c.setFont("Helvetica", 7.5)
    c.drawString(x, y, label)
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y - 5 * mm, value)
