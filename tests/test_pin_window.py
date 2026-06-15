"""
test_pin_window.py
==================
Tests for the PIN time-window, single-use, and invalidation rules.

Rules verified:
  - PIN rejected > 5 min before scheduled time
  - PIN accepted at exactly T-5
  - PIN accepted during exam window
  - PIN rejected after pin_window_end
  - PIN invalidated after submit — replay returns invalid
  - pin_active=False blocks PIN regardless of time
"""

import datetime as dt

import pytest
from freezegun import freeze_time

from .conftest import BEFORE_WINDOW, AT_WINDOW_START, INSIDE_WINDOW, AFTER_WINDOW, make_answers


URL = "/exams/validate-pin/"


# ─── helpers ─────────────────────────────────────────────────────────────────
def validate(client, session, pin="123456"):
    # Serializer expects snake_case: session_id, pin
    return client.post(URL, {"session_id": str(session.id), "pin": pin}, format="json")


# ─── PIN timing ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(BEFORE_WINDOW)
def test_pin_rejected_before_window(learner_client, session):
    """6 minutes before T = outside window → 400."""
    r = validate(learner_client, session)
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


@pytest.mark.django_db
@freeze_time(AT_WINDOW_START)
def test_pin_accepted_at_window_start(learner_client, session):
    """Exactly T-5 min = window open → 200 with questions."""
    r = validate(learner_client, session)
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["valid"] is True
    assert len(body["data"]["examQuestions"]) == session.exam_config.questions_per_exam


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_pin_accepted_during_window(learner_client, session):
    """During the exam window → 200."""
    r = validate(learner_client, session)
    assert r.status_code == 200
    assert r.json()["data"]["valid"] is True


@pytest.mark.django_db
@freeze_time(AFTER_WINDOW)
def test_pin_rejected_after_window_end(learner_client, session):
    """1 minute past pin_window_end → 400."""
    r = validate(learner_client, session)
    assert r.status_code == 400
    assert r.json()["success"] is False


# ─── PIN content ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_pin_wrong_value_rejected(learner_client, session):
    """Correct session, wrong PIN → 400."""
    r = validate(learner_client, session, pin="000000")
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_pin_inactive_blocked(learner_client, session):
    """pin_active=False blocks even during window."""
    session.pin_active = False
    session.save(update_fields=["pin_active"])
    r = validate(learner_client, session)
    assert r.status_code == 400


# ─── Questions never include correct answers ──────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_validate_pin_no_correct_answers_in_response(learner_client, session):
    """Questions must NOT expose correctAnswers or explanation."""
    r = validate(learner_client, session)
    assert r.status_code == 200
    for q in r.json()["data"]["examQuestions"]:
        assert "correctAnswers" not in q
        assert "correct_answers" not in q
        assert "explanation" not in q


# ─── Session state transitions ────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_pin_sets_session_to_in_progress(learner_client, session):
    """First valid PIN entry → status becomes in_progress."""
    assert session.status == "scheduled"
    r = validate(learner_client, session)
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.status == "in_progress"
    assert session.started_at is not None


@pytest.mark.django_db
def test_time_taken_after_invigilator_unlock_before_pin(invigilator_client, learner_client, session):
    """
    Invigilator "Unlock Test" flips status to in_progress before the learner
    enters their PIN. started_at must still be recorded on PIN entry — and
    submit's time_taken_seconds must reflect the real elapsed time, not 0.
    """
    start = INSIDE_WINDOW
    end = start + dt.timedelta(minutes=25, seconds=13)

    with freeze_time(start):
        r = invigilator_client.post(f"/exams/sessions/{session.id}/unlock/")
        assert r.status_code == 200

    session.refresh_from_db()
    assert session.status == "in_progress"
    assert session.started_at is None

    with freeze_time(start):
        r = validate(learner_client, session)
        assert r.status_code == 200

    session.refresh_from_db()
    assert session.started_at == start

    with freeze_time(end):
        r = learner_client.post(
            f"/exams/{session.id}/submit/",
            {"session_id": str(session.id), "answers": make_answers(session.question_set)},
            format="json",
        )
        assert r.status_code in (200, 201)
        assert r.json()["data"]["time_taken_seconds"] == 25 * 60 + 13


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_completed_session_pin_rejected(learner_client, session):
    """Completed session → PIN rejected even if within window."""
    session.status = "completed"
    session.save(update_fields=["status"])
    r = validate(learner_client, session)
    assert r.status_code == 400


# ─── Single-use: PIN invalidated after submit ────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_pin_invalidated_after_submit(learner_client, session):
    """After submit/, re-validating the PIN on the completed session must return 400."""
    r1 = validate(learner_client, session)
    assert r1.status_code == 200

    answers = [
        {"questionId": qid, "selected": [0]}
        for qid in session.question_set
    ]
    r_submit = learner_client.post(
        f"/exams/{session.id}/submit/",
        {"session_id": str(session.id), "answers": answers},
        format="json",
    )
    assert r_submit.status_code in (200, 201)

    # Completed session → 400 on re-validate
    r2 = validate(learner_client, session)
    assert r2.status_code == 400
    assert r2.json()["success"] is False


# ─── Resume: draft returned on re-entry ──────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_resume_returns_saved_draft(learner_client, in_progress_session):
    """Re-entering an in_progress session returns the saved draft."""
    sess = in_progress_session
    qid = sess.question_set[0]
    sess.draft_answers = [{"questionId": qid, "selected": [1]}]
    sess.draft_current_question_index = 2
    sess.draft_remaining_seconds = 3000
    sess.draft_updated_at = INSIDE_WINDOW
    sess.save(update_fields=[
        "draft_answers", "draft_current_question_index",
        "draft_remaining_seconds", "draft_updated_at",
    ])

    r = validate(learner_client, sess)
    assert r.status_code == 200
    draft = r.json()["data"]["draft"]
    assert draft is not None
    # The view returns camelCase keys in the draft dict
    assert draft["currentQuestionIndex"] == 2
    assert draft["remainingSeconds"] == 3000


# ─── Wrong learner cannot use another learner's session ──────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_wrong_learner_cannot_enter_session(learner2_client, session):
    """A different learner's token → 403."""
    r = learner2_client.post(
        URL,
        {"session_id": str(session.id), "pin": "123456"},
        format="json",
    )
    assert r.status_code == 403
