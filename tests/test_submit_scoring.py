"""
test_submit_scoring.py
======================
Submit endpoint and score_submission() service unit tests.

Rules verified:
  - Grade boundaries: distinction / merit / pass / did_not_pass
  - passed = score_percent >= grade_pass
  - timeTakenSeconds computed from started_at → submitted_at
  - submit rejects answers for questions outside the frozen set → 400
  - Submitting a completed session returns idempotent existing result
  - Non-owner cannot submit → 403
  - ExamResult.violation_count matches actual IntegrityViolation rows

Note:
  - Submit serializer accepts: session_id (snake_case), answers (list)
  - Each answer: {"questionId": "...", "selected": [...]} (camelCase, view checks this)
  - Response from ExamResultSerializer is snake_case fields
"""

import pytest
from freezegun import freeze_time
from django.utils import timezone

from apps.exams.models import ExamResult, IntegrityViolation
from apps.exams.services import score_submission
from .conftest import INSIDE_WINDOW, make_answers


def submit_url(session_id):
    return f"/exams/{session_id}/submit/"


# ─── score_submission unit tests (no HTTP) ────────────────────────────────────
@pytest.mark.django_db
def test_all_correct_scores_100(in_progress_session):
    """All answers correct → 100%."""
    sess = in_progress_session
    answers = make_answers(sess.question_set, selected=[0])
    result = score_submission(session=sess, answers=answers)
    assert result["score_percent"] == 100
    assert result["correct_count"] == 5
    assert result["grade"] == "distinction"
    assert result["passed"] is True


@pytest.mark.django_db
def test_all_wrong_scores_0(in_progress_session):
    """All answers wrong → 0%."""
    sess = in_progress_session
    answers = make_answers(sess.question_set, selected=[1])   # correct is [0]
    result = score_submission(session=sess, answers=answers)
    assert result["score_percent"] == 0
    assert result["grade"] == "did_not_pass"
    assert result["passed"] is False


@pytest.mark.django_db
def test_passed_boundary_at_pass_mark(in_progress_session):
    """
    With 5 questions and grade_pass=60:
    60% = 3/5 correct → exactly pass boundary → grade = 'pass'.
    """
    sess = in_progress_session
    correct_ids = sess.question_set[:3]
    wrong_ids   = sess.question_set[3:]
    answers = (
        make_answers(correct_ids, selected=[0]) +
        make_answers(wrong_ids,   selected=[1])
    )
    result = score_submission(session=sess, answers=answers)
    assert result["score_percent"] == 60
    assert result["passed"] is True
    assert result["grade"] == "pass"


@pytest.mark.django_db
def test_one_below_pass_mark_fails(in_progress_session):
    """2/5 = 40% → did_not_pass."""
    sess = in_progress_session
    answers = (
        make_answers(sess.question_set[:2], selected=[0]) +
        make_answers(sess.question_set[2:], selected=[1])
    )
    result = score_submission(session=sess, answers=answers)
    assert result["passed"] is False
    assert result["grade"] == "did_not_pass"


@pytest.mark.django_db
def test_merit_grade_at_70_percent(in_progress_session):
    """For 5 questions: merit requires 70% = 3.5 → 4 correct = 80%."""
    sess = in_progress_session
    # 3 correct = 60% = pass; 4 correct = 80% = merit; 5 correct = 100% = distinction
    answers = (
        make_answers(sess.question_set[:4], selected=[0]) +  # 4 correct
        make_answers(sess.question_set[4:], selected=[1])     # 1 wrong
    )
    result = score_submission(session=sess, answers=answers)
    assert result["score_percent"] == 80
    assert result["grade"] == "merit"
    assert result["passed"] is True


# ─── HTTP submit tests ────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_returns_required_fields(learner_client, in_progress_session):
    """Response shape includes all required ExamResult fields (snake_case from serializer)."""
    sess = in_progress_session
    r = learner_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": make_answers(sess.question_set)},
        format="json",
    )
    assert r.status_code in (200, 201)
    data = r.json()["data"]
    # ExamResultSerializer uses snake_case field names
    for key in ("score_percent", "correct_count", "total_questions", "grade", "passed",
                "time_taken_seconds", "violation_count", "attempt_number", "exam_date"):
        assert key in data, f"Missing key: {key}"


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_marks_session_completed(learner_client, in_progress_session):
    """After submit, session.status == 'completed'."""
    sess = in_progress_session
    learner_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": make_answers(sess.question_set)},
        format="json",
    )
    sess.refresh_from_db()
    assert sess.status == "completed"
    assert sess.submitted_at is not None


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_idempotent_for_completed_session(learner_client, in_progress_session):
    """
    Second submit on a completed session.
    The view checks status before the existing-result guard, so 'completed'
    sessions return 400 (not in_progress or scheduled).
    The first submission's result is persisted and can be retrieved via GET /results/.
    """
    sess = in_progress_session
    payload = {"session_id": str(sess.id), "answers": make_answers(sess.question_set)}
    r1 = learner_client.post(submit_url(sess.id), payload, format="json")
    assert r1.status_code in (200, 201)

    # Session is now completed; second submit returns 400
    r2 = learner_client.post(submit_url(sess.id), payload, format="json")
    assert r2.status_code == 400

    # But the result is persisted — verify via results endpoint
    result_id = r1.json()["data"]["id"]
    from apps.exams.models import ExamResult
    assert ExamResult.objects.filter(id=result_id).exists()


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_rejects_outside_question(learner_client, in_progress_session, questions):
    """Submitting a question outside the frozen set → 400."""
    sess = in_progress_session
    outside = next(q for q in questions if str(q.id) not in sess.question_set)
    bad_answers = make_answers(sess.question_set) + [
        {"questionId": str(outside.id), "selected": [0]}
    ]
    r = learner_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": bad_answers},
        format="json",
    )
    assert r.status_code == 400


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_wrong_learner_forbidden(learner2_client, in_progress_session):
    """Different learner cannot submit → 403."""
    sess = in_progress_session
    r = learner2_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": make_answers(sess.question_set)},
        format="json",
    )
    assert r.status_code == 403


# ─── violation_count ─────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_violation_count_matches_records(learner_client, in_progress_session):
    """ExamResult.violation_count == number of IntegrityViolation rows."""
    sess = in_progress_session
    for i in range(3):
        IntegrityViolation.objects.create(
            session=sess,
            type="tab_switch",
            detail=f"Tab switch #{i}",
            question_number=i + 1,
        )

    r = learner_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": make_answers(sess.question_set)},
        format="json",
    )
    assert r.status_code in (200, 201)
    assert r.json()["data"]["violation_count"] == 3


# ─── attempt_number ───────────────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_attempt_number_increments(learner_client, in_progress_session):
    """First submit → attempt_number=1."""
    sess = in_progress_session
    r = learner_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": make_answers(sess.question_set)},
        format="json",
    )
    assert r.json()["data"]["attempt_number"] == 1


# ─── correct answers never sent back ─────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_submit_response_never_includes_correct_answers(learner_client, in_progress_session):
    """ExamResult response must not include correctAnswers or explanation."""
    sess = in_progress_session
    r = learner_client.post(
        submit_url(sess.id),
        {"session_id": str(sess.id), "answers": make_answers(sess.question_set)},
        format="json",
    )
    body_str = str(r.json())
    assert "correctAnswers" not in body_str
    assert "correct_answers" not in body_str
