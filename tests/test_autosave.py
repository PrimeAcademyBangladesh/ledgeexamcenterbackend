"""
test_autosave.py
================
Autosave (PATCH /sessions/{id}/draft/) rules.

Rules verified:
  - Draft allowed while status=in_progress
  - Draft rejected when session is completed or cancelled
  - Draft updates stored draft fields on the session
  - Draft rejected if questionId outside frozen set
  - Non-owner learner cannot draft to another learner's session
  - Admin / invigilator cannot use the draft endpoint (learner-only)

Note: Serializer expects snake_case input fields:
  session_id, current_question_index, flagged_question_indexes, remaining_seconds
  The response dict is camelCase (manually built in the view).
"""

import pytest
from freezegun import freeze_time

from .conftest import INSIDE_WINDOW, make_answers


def draft_url(session_id):
    return f"/exams/sessions/{session_id}/draft/"


def _draft_payload(session, answers=None, index=1, flagged=None, remaining=3000):
    # Serializer field names are snake_case
    return {
        "session_id": str(session.id),
        "answers": answers if answers is not None else make_answers(session.question_set),
        "current_question_index": index,
        "flagged_question_indexes": flagged or [],
        "remaining_seconds": remaining,
    }


# ─── happy path ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_accepted_while_in_progress(learner_client, in_progress_session):
    """200 response and draft fields persisted. Response keys are camelCase."""
    sess = in_progress_session
    payload = _draft_payload(sess, index=3, flagged=[1, 4], remaining=2800)
    r = learner_client.patch(draft_url(sess.id), payload, format="json")

    assert r.status_code == 200
    data = r.json()["data"]
    # The view returns camelCase keys in the response dict
    assert data["currentQuestionIndex"] == 3
    assert data["flaggedQuestionIndexes"] == [1, 4]
    assert data["remainingSeconds"] == 2800
    assert data["updatedAt"] is not None

    sess.refresh_from_db()
    assert sess.draft_current_question_index == 3
    assert sess.draft_flagged_question_indexes == [1, 4]
    assert sess.draft_remaining_seconds == 2800


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_on_scheduled_session_transitions_to_in_progress(learner_client, session):
    """PATCH /draft/ on a scheduled session transitions it to in_progress."""
    assert session.status == "scheduled"
    r = learner_client.patch(draft_url(session.id), _draft_payload(session), format="json")
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.status == "in_progress"
    assert session.started_at is not None


# ─── blocked states ──────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_rejected_when_completed(learner_client, in_progress_session):
    """Completed session → 400."""
    sess = in_progress_session
    sess.status = "completed"
    sess.save(update_fields=["status"])
    r = learner_client.patch(draft_url(sess.id), _draft_payload(sess), format="json")
    assert r.status_code == 400
    assert r.json()["success"] is False


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_rejected_when_cancelled(learner_client, in_progress_session):
    """Cancelled session → 400."""
    sess = in_progress_session
    sess.status = "cancelled"
    sess.save(update_fields=["status"])
    r = learner_client.patch(draft_url(sess.id), _draft_payload(sess), format="json")
    assert r.status_code == 400


# ─── wrong question ───────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_rejects_outside_question(learner_client, in_progress_session, questions):
    """Including a question outside the frozen set → 400."""
    sess = in_progress_session
    outside = next(q for q in questions if str(q.id) not in sess.question_set)
    bad_answers = make_answers([outside.id])
    r = learner_client.patch(draft_url(sess.id), _draft_payload(sess, answers=bad_answers), format="json")
    assert r.status_code == 400


# ─── ownership ───────────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_forbidden_for_wrong_learner(learner2_client, in_progress_session):
    """A different learner cannot autosave to someone else's session."""
    sess = in_progress_session
    r = learner2_client.patch(draft_url(sess.id), _draft_payload(sess), format="json")
    # 403 or 404 depending on queryset scoping (learner2 can't see learner1's session)
    assert r.status_code in (403, 404)


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_forbidden_for_admin(admin_client, in_progress_session):
    """Admin cannot use the learner-only draft endpoint."""
    sess = in_progress_session
    r = admin_client.patch(draft_url(sess.id), _draft_payload(sess), format="json")
    assert r.status_code == 403


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_forbidden_for_invigilator(invigilator_client, in_progress_session):
    """Invigilator cannot use the draft endpoint."""
    sess = in_progress_session
    r = invigilator_client.patch(draft_url(sess.id), _draft_payload(sess), format="json")
    assert r.status_code == 403


# ─── idempotency ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_multiple_drafts_keep_latest(learner_client, in_progress_session):
    """Sequential drafts — later one wins."""
    sess = in_progress_session
    learner_client.patch(draft_url(sess.id), _draft_payload(sess, index=1, remaining=3500), format="json")
    learner_client.patch(draft_url(sess.id), _draft_payload(sess, index=4, remaining=2000), format="json")
    sess.refresh_from_db()
    assert sess.draft_current_question_index == 4
    assert sess.draft_remaining_seconds == 2000
