"""
test_frozen_questions.py
========================
Verifies that ExamSession.question_set is frozen at creation and that submit
rejects any question not in the frozen set.

Rules verified:
  - question_set is set at session creation, not at PIN validation
  - validate-pin returns the same questions on re-validation (resume)
  - submit/ rejects answers for questionId not in frozen set → 400
  - Questions written to LearnerSeenQuestion immediately on session creation
  - Session without a question_set is blocked at PIN validation
"""

import pytest
from freezegun import freeze_time

from apps.exams.models import LearnerSeenQuestion
from apps.exams.services import create_scheduled_session
from .conftest import INSIDE_WINDOW, EXAM_DATE, EXAM_TIME, make_answers


VALIDATE_URL = "/exams/validate-pin/"


# ─── question_set frozen at creation ─────────────────────────────────────────
@pytest.mark.django_db
def test_question_set_frozen_at_session_creation(session, questions):
    """question_set is populated on session creation, not on PIN entry."""
    assert len(session.question_set) == 5
    all_ids = [str(q.id) for q in questions]
    for qid in session.question_set:
        assert qid in all_ids


@pytest.mark.django_db
def test_seen_questions_created_at_session_creation(session, learner_user):
    """LearnerSeenQuestion rows exist immediately after session creation."""
    seen_ids = set(str(s) for s in LearnerSeenQuestion.objects.filter(
        learner=learner_user
    ).values_list("question_id", flat=True))
    for qid in session.question_set:
        assert qid in seen_ids


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_validate_pin_returns_frozen_question_set(learner_client, session):
    """PIN validation returns exactly the frozen question_set in order."""
    r = learner_client.post(
        VALIDATE_URL,
        {"session_id": str(session.id), "pin": "123456"},
        format="json",
    )
    assert r.status_code == 200
    returned_ids = [q["id"] for q in r.json()["data"]["examQuestions"]]
    assert returned_ids == session.question_set


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_validate_pin_same_questions_on_resume(learner_client, in_progress_session):
    """Re-entering in_progress session returns identical frozen questions."""
    sess = in_progress_session
    r1 = learner_client.post(
        VALIDATE_URL, {"session_id": str(sess.id), "pin": "123456"}, format="json"
    )
    r2 = learner_client.post(
        VALIDATE_URL, {"session_id": str(sess.id), "pin": "123456"}, format="json"
    )
    ids1 = [q["id"] for q in r1.json()["data"]["examQuestions"]]
    ids2 = [q["id"] for q in r2.json()["data"]["examQuestions"]]
    assert ids1 == ids2 == sess.question_set


# ─── submit rejects out-of-set questions ─────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_rejects_question_outside_frozen_set(
    learner_client, in_progress_session, questions
):
    """Submitting a questionId not in the frozen set → 400."""
    sess = in_progress_session
    frozen_ids = set(sess.question_set)
    outside_question = next(q for q in questions if str(q.id) not in frozen_ids)

    answers = make_answers(sess.question_set) + [
        {"questionId": str(outside_question.id), "selected": [0]}
    ]
    r = learner_client.post(
        f"/exams/{sess.id}/submit/",
        {"session_id": str(sess.id), "answers": answers},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["success"] is False


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_accepts_valid_frozen_answers(learner_client, in_progress_session):
    """Submitting only frozen-set questions → 200/201."""
    sess = in_progress_session
    answers = make_answers(sess.question_set)
    r = learner_client.post(
        f"/exams/{sess.id}/submit/",
        {"session_id": str(sess.id), "answers": answers},
        format="json",
    )
    assert r.status_code in (200, 201)
    assert "score_percent" in r.json()["data"]


# ─── session without question_set blocked ────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_validate_pin_blocked_when_no_question_set(learner_client, session):
    """If question_set is empty, validate-pin returns 400 with a config error."""
    session.question_set = []
    session.save(update_fields=["question_set"])
    r = learner_client.post(
        VALIDATE_URL,
        {"session_id": str(session.id), "pin": "123456"},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["success"] is False


# ─── question count assertion ─────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_create_session_sets_correct_question_count(
    db, exam_config, learner_user, invigilator_user, enrollment, questions
):
    """create_scheduled_session asserts question_set length == questions_per_exam."""
    sess = create_scheduled_session(
        exam_config=exam_config,
        learner=learner_user,
        invigilator=invigilator_user,
        scheduled_date=EXAM_DATE,
        scheduled_time=EXAM_TIME,
        enrollment=enrollment,
    )
    assert len(sess.question_set) == exam_config.questions_per_exam


# ─── draft autosave validates against frozen set ──────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_draft_rejects_question_outside_frozen_set(
    learner_client, in_progress_session, questions
):
    """PATCH /draft/ with a questionId outside frozen set → 400."""
    sess = in_progress_session
    frozen_ids = set(sess.question_set)
    outside = next(q for q in questions if str(q.id) not in frozen_ids)

    r = learner_client.patch(
        f"/exams/sessions/{sess.id}/draft/",
        {
            "session_id": str(sess.id),
            "answers": [{"questionId": str(outside.id), "selected": [0]}],
            "current_question_index": 0,
            "flagged_question_indexes": [],
            "remaining_seconds": 3000,
        },
        format="json",
    )
    assert r.status_code == 400
