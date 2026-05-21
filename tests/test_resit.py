"""
test_resit.py
=============
Resit eligibility, question exclusion, and insufficient-pool rules.

Rules verified:
  - is_resit_eligible() logic: pass_mark - 10 <= score < pass_mark
  - Learner who passed cannot create resit → 400
  - Learner who failed within 10% margin is eligible
  - Learner who failed below 10% margin is blocked → 400
  - Resit session excludes previously seen questions
  - Insufficient unseen questions → 400 / ValidationError
  - Duplicate pending retake request blocked → 400
"""

import pytest
from django.utils import timezone

from apps.exams.models import ExamConfig, ExamResult, ExamSession, LearnerSeenQuestion
from apps.exams.services import is_resit_eligible, create_scheduled_session
from .conftest import EXAM_DATE, EXAM_TIME


RESIT_URL = "/exams/retakes/resit/"
RETAKE_REQUEST_URL = "/exams/retakes/request/"


# ─── is_resit_eligible unit tests ────────────────────────────────────────────
@pytest.mark.django_db
def test_is_resit_eligible_within_margin():
    """Score >= pass - 10 and < pass → eligible."""
    assert is_resit_eligible(score_percent=55, pass_mark=60) is True
    assert is_resit_eligible(score_percent=50, pass_mark=60) is True
    assert is_resit_eligible(score_percent=59, pass_mark=60) is True


@pytest.mark.django_db
def test_is_resit_eligible_below_margin():
    """Score < pass - 10 → not eligible."""
    assert is_resit_eligible(score_percent=49, pass_mark=60) is False
    assert is_resit_eligible(score_percent=0, pass_mark=60) is False


@pytest.mark.django_db
def test_is_resit_eligible_passed():
    """Score >= pass → not eligible (already passed)."""
    assert is_resit_eligible(score_percent=60, pass_mark=60) is False
    assert is_resit_eligible(score_percent=100, pass_mark=60) is False


# ─── Helper to build a completed ExamResult ──────────────────────────────────
def _make_result(session, score_percent, passed, grade="did_not_pass"):
    session.status = "completed"
    session.submitted_at = timezone.now()
    session.save(update_fields=["status", "submitted_at"])
    return ExamResult.objects.create(
        session=session,
        learner=session.learner,
        exam_config=session.exam_config,
        qualification=session.exam_config.qualification,
        score_percent=score_percent,
        correct_count=int(score_percent / 100 * session.exam_config.questions_per_exam),
        total_questions=session.exam_config.questions_per_exam,
        grade=grade,
        passed=passed,
        time_taken_seconds=3600,
        exam_date=session.scheduled_date,
    )


# ─── API: resit session creation ─────────────────────────────────────────────
@pytest.mark.django_db
def test_resit_blocked_if_learner_passed(
    invigilator_client, session, invigilator_user
):
    """Passed learner → resit endpoint returns 400."""
    result = _make_result(session, score_percent=80, passed=True, grade="merit")
    r = invigilator_client.post(
        RESIT_URL,
        {"previous_result_id": str(result.id), "invigilator_id": str(invigilator_user.id)},
        format="json",
    )
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False


@pytest.mark.django_db
def test_resit_blocked_if_score_too_low(
    invigilator_client, session, invigilator_user
):
    """Score < pass_mark - 10 → resit endpoint returns 400."""
    result = _make_result(session, score_percent=40, passed=False)
    r = invigilator_client.post(
        RESIT_URL,
        {"previous_result_id": str(result.id), "invigilator_id": str(invigilator_user.id)},
        format="json",
    )
    assert r.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_resit_session_created_for_eligible_learner(
    invigilator_client, session, invigilator_user, questions
):
    """Score within 10% of pass → resit session created (201)."""
    result = _make_result(session, score_percent=55, passed=False)
    r = invigilator_client.post(
        RESIT_URL,
        {"previous_result_id": str(result.id), "invigilator_id": str(invigilator_user.id)},
        format="json",
    )
    assert r.status_code == 201, r.json()
    data = r.json()["data"]
    assert data["status"] == "scheduled"
    # question_ids is the ExamSessionSerializer field name for question_set
    assert len(data["question_ids"]) == 5


@pytest.mark.django_db(transaction=True)
def test_resit_session_excludes_seen_questions(
    db, invigilator_user, learner_user, enrollment, exam_config, questions
):
    """Resit question_set shares no IDs with the learner's seen questions."""
    first_sess = create_scheduled_session(
        exam_config=exam_config,
        learner=learner_user,
        invigilator=invigilator_user,
        scheduled_date=EXAM_DATE,
        scheduled_time=EXAM_TIME,
        enrollment=enrollment,
    )
    first_seen = set(first_sess.question_set)

    first_sess.status = "completed"
    first_sess.save(update_fields=["status"])
    result = ExamResult.objects.create(
        session=first_sess,
        learner=learner_user,
        exam_config=exam_config,
        qualification=exam_config.qualification,
        score_percent=55,
        correct_count=2,
        total_questions=5,
        grade="did_not_pass",
        passed=False,
        time_taken_seconds=3600,
        exam_date=EXAM_DATE,
    )

    assert is_resit_eligible(55, exam_config.grade_pass)

    resit_sess = create_scheduled_session(
        exam_config=exam_config,
        learner=learner_user,
        invigilator=invigilator_user,
        scheduled_date=EXAM_DATE,
        scheduled_time=EXAM_TIME,
        enrollment=enrollment,
        previous_result=result,
    )
    resit_seen = set(resit_sess.question_set)

    assert first_seen.isdisjoint(resit_seen), (
        f"Overlap found: {first_seen & resit_seen}"
    )


@pytest.mark.django_db(transaction=True)
def test_resit_blocked_insufficient_unseen_questions(
    db, learner_user, invigilator_user, qualification
):
    """
    When the pool equals questions_per_exam and all are seen, resit must raise.
    """
    from rest_framework.exceptions import ValidationError as DRFValidationError
    from apps.users.models import LearnerProfile
    from apps.learners.models import Enrollment, EnrollmentStatus
    from apps.questions.models import Question

    cfg = ExamConfig.objects.create(
        title="Tight Pool Exam",
        qualification=qualification,
        exam_type="live",
        questions_per_exam=5,
        time_limit_minutes=60,
        grade_distinction=85,
        grade_merit=70,
        grade_pass=60,
        status="published",
    )
    for i in range(5):
        Question.objects.create(
            qualification=qualification,
            question_text=f"Tight question {i}?",
            question_type="single",
            options=["A", "B", "C", "D"],
            correct_answers=[0],
            is_active=True,
        )

    profile = LearnerProfile.objects.get(user=learner_user)
    enroll = Enrollment.objects.create(
        learner=profile,
        qualification=qualification,
        cohort="2026-Tight",
        status=EnrollmentStatus.ACTIVE,
        enrolled_at="2026-01-01T00:00:00Z",
    )

    first = create_scheduled_session(
        exam_config=cfg,
        learner=learner_user,
        invigilator=invigilator_user,
        scheduled_date=EXAM_DATE,
        scheduled_time=EXAM_TIME,
        enrollment=enroll,
    )
    first.status = "completed"
    first.save(update_fields=["status"])
    result = ExamResult.objects.create(
        session=first,
        learner=learner_user,
        exam_config=cfg,
        qualification=qualification,
        score_percent=55,
        correct_count=2,
        total_questions=5,
        grade="did_not_pass",
        passed=False,
        time_taken_seconds=3600,
        exam_date=EXAM_DATE,
    )

    with pytest.raises(DRFValidationError):
        create_scheduled_session(
            exam_config=cfg,
            learner=learner_user,
            invigilator=invigilator_user,
            scheduled_date=EXAM_DATE,
            scheduled_time=EXAM_TIME,
            enrollment=enroll,
            previous_result=result,
        )


# ─── Retake request ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_duplicate_retake_request_blocked(learner_client, session, learner_user):
    """Submitting a second pending retake for the same result → 400."""
    result = _make_result(session, score_percent=55, passed=False)
    payload = {
        "learner_id": str(learner_user.id),
        "exam_config_id": str(session.exam_config.id),
        "previous_result_id": str(result.id),
    }
    r1 = learner_client.post(RETAKE_REQUEST_URL, payload, format="json")
    assert r1.status_code == 201

    r2 = learner_client.post(RETAKE_REQUEST_URL, payload, format="json")
    assert r2.status_code == 400
    assert r2.json()["success"] is False


@pytest.mark.django_db
def test_retake_request_for_failed_exam_accepted(learner_client, session, learner_user):
    """Retake request for a failed result is accepted (admin approves later)."""
    result = _make_result(session, score_percent=55, passed=False)
    r = learner_client.post(
        RETAKE_REQUEST_URL,
        {
            "learner_id": str(learner_user.id),
            "exam_config_id": str(session.exam_config.id),
            "previous_result_id": str(result.id),
        },
        format="json",
    )
    assert r.status_code == 201
    assert r.json()["data"]["status"] == "pending"
