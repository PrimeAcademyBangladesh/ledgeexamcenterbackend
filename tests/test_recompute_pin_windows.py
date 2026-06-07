"""
test_recompute_pin_windows.py
=============================
Covers the one-off `recompute_pin_windows` management command that repairs
sessions whose pin_window_start/end were computed by the old buggy
(force-UTC) version of _compute_pin_window — see apps/exams/services.py.
"""
import datetime as dt
from io import StringIO

import pytest
from django.core.management import call_command

from apps.exams.services import _compute_pin_window
from .conftest import EXAM_DATE, EXAM_TIME


def _buggy_window(scheduled_date, scheduled_time, exam_config):
    """Recreate the pre-fix computation: scheduled_time force-tagged as UTC."""
    start_dt = dt.datetime.combine(scheduled_date, scheduled_time, tzinfo=dt.timezone.utc)
    return start_dt - dt.timedelta(minutes=5), start_dt + dt.timedelta(minutes=exam_config.time_limit_minutes)


@pytest.mark.django_db
def test_dry_run_reports_drift_without_writing(session):
    correct_start, correct_end = _compute_pin_window(EXAM_DATE, EXAM_TIME, session.exam_config)
    buggy_start, buggy_end = _buggy_window(EXAM_DATE, EXAM_TIME, session.exam_config)
    assert buggy_start != correct_start  # sanity: BST means the two diverge

    session.pin_window_start = buggy_start
    session.pin_window_end = buggy_end
    session.save(update_fields=["pin_window_start", "pin_window_end"])

    out = StringIO()
    call_command("recompute_pin_windows", stdout=out)

    session.refresh_from_db()
    assert session.pin_window_start == buggy_start  # untouched without --apply
    assert session.pin_window_end == buggy_end
    assert "would change" in out.getvalue()


@pytest.mark.django_db
def test_apply_corrects_drifted_window(session):
    correct_start, correct_end = _compute_pin_window(EXAM_DATE, EXAM_TIME, session.exam_config)
    buggy_start, buggy_end = _buggy_window(EXAM_DATE, EXAM_TIME, session.exam_config)

    session.pin_window_start = buggy_start
    session.pin_window_end = buggy_end
    session.save(update_fields=["pin_window_start", "pin_window_end"])

    out = StringIO()
    call_command("recompute_pin_windows", "--apply", stdout=out)

    session.refresh_from_db()
    assert session.pin_window_start == correct_start
    assert session.pin_window_end == correct_end
    assert "Updated 1 session" in out.getvalue()


@pytest.mark.django_db
def test_already_correct_session_is_left_alone(session):
    """The `session` fixture is already built with the corrected window."""
    before_start, before_end = session.pin_window_start, session.pin_window_end

    out = StringIO()
    call_command("recompute_pin_windows", "--apply", stdout=out)

    session.refresh_from_db()
    assert session.pin_window_start == before_start
    assert session.pin_window_end == before_end
    assert "No sessions needed recomputation" in out.getvalue()


@pytest.mark.django_db
def test_sit_now_session_is_skipped(session):
    """allow_immediate_start sessions anchor their window to activation time, not
    scheduled_date/time — recomputing would wrongly reset it to "now"."""
    session.allow_immediate_start = True
    session.pin_window_start = dt.datetime(2026, 5, 21, 8, 0, tzinfo=dt.timezone.utc)
    session.pin_window_end = dt.datetime(2026, 5, 21, 9, 0, tzinfo=dt.timezone.utc)
    session.save(update_fields=["allow_immediate_start", "pin_window_start", "pin_window_end"])
    before_start, before_end = session.pin_window_start, session.pin_window_end

    call_command("recompute_pin_windows", "--apply", stdout=StringIO())

    session.refresh_from_db()
    assert session.pin_window_start == before_start
    assert session.pin_window_end == before_end


@pytest.mark.django_db
def test_completed_session_is_skipped(session):
    session.status = "completed"
    session.pin_window_start, session.pin_window_end = _buggy_window(EXAM_DATE, EXAM_TIME, session.exam_config)
    session.save(update_fields=["status", "pin_window_start", "pin_window_end"])
    before_start, before_end = session.pin_window_start, session.pin_window_end

    call_command("recompute_pin_windows", "--apply", stdout=StringIO())

    session.refresh_from_db()
    assert session.pin_window_start == before_start
    assert session.pin_window_end == before_end
