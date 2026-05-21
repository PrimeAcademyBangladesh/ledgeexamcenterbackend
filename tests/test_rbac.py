"""
test_rbac.py
============
Role-Based Access Control — every protected endpoint returns 403 for wrong roles.

Rules verified:
  - Learner cannot POST /exams/ (create ExamConfig) → 403
  - Learner cannot POST /exams/sessions/ → 403
  - Invigilator cannot POST /exams/ → 403
  - Invigilator cannot POST /exams/sessions/ → 403
  - Learner can only GET their own sessions (other learner → filtered out)
  - Invigilator can only GET sessions assigned to them
  - Admin sees all sessions
  - Unauthenticated requests → 401
  - Validate-PIN is learner-only → admin/invigilator get 403
  - Resit endpoint is invigilator/admin-only → learner gets 403
  - Results: learner sees own only; other learner does not see them
  - Retake approve/deny is admin-only → learner/invigilator get 403
"""

import pytest
from freezegun import freeze_time
from rest_framework.test import APIClient

from .conftest import INSIDE_WINDOW


EXAMS_URL = "/exams/"
SESSIONS_URL = "/exams/sessions/"
VALIDATE_PIN_URL = "/exams/validate-pin/"
RESIT_URL = "/exams/retakes/resit/"
RESULTS_URL = "/exams/results/"


# ─── ExamConfig creation ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_learner_cannot_create_exam_config(learner_client, qualification):
    """Learner → 403 on POST /exams/."""
    r = learner_client.post(
        EXAMS_URL,
        {
            "title": "Malicious Exam",
            "qualification_id": str(qualification.id),
            "exam_type": "live",
            "questions_per_exam": 5,
            "time_limit_minutes": 60,
        },
        format="json",
    )
    assert r.status_code == 403


@pytest.mark.django_db
def test_invigilator_cannot_create_exam_config(invigilator_client, qualification):
    """Invigilator → 403 on POST /exams/."""
    r = invigilator_client.post(
        EXAMS_URL,
        {"title": "x", "qualification_id": str(qualification.id)},
        format="json",
    )
    assert r.status_code == 403


@pytest.mark.django_db
def test_admin_can_read_exam_configs(admin_client):
    """Admin → 200 on GET /exams/."""
    r = admin_client.get(EXAMS_URL)
    assert r.status_code == 200


@pytest.mark.django_db
def test_invigilator_can_read_exam_configs(invigilator_client):
    """Invigilator (read-only staff) → 200 on GET /exams/."""
    r = invigilator_client.get(EXAMS_URL)
    assert r.status_code == 200


@pytest.mark.django_db
def test_learner_cannot_read_exam_configs(learner_client):
    """Learner → 403 on GET /exams/ (admin-or-staff-only via IsAdminOrReadOnlyForStaff)."""
    r = learner_client.get(EXAMS_URL)
    assert r.status_code == 403


# ─── Session creation ─────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_learner_cannot_create_session(learner_client, exam_config, learner_user, invigilator_user):
    """Learner → 403 on POST /exams/sessions/."""
    r = learner_client.post(
        SESSIONS_URL,
        {
            "exam_config_id": str(exam_config.id),
            "learner_id": str(learner_user.id),
            "invigilator_id": str(invigilator_user.id),
            "scheduled_date": "2026-06-01",
            "scheduled_time": "10:00",
        },
        format="json",
    )
    assert r.status_code == 403


@pytest.mark.django_db
def test_invigilator_cannot_create_session(invigilator_client, exam_config, learner_user, invigilator_user):
    """Invigilator → 403 on POST /exams/sessions/."""
    r = invigilator_client.post(
        SESSIONS_URL,
        {
            "exam_config_id": str(exam_config.id),
            "learner_id": str(learner_user.id),
            "invigilator_id": str(invigilator_user.id),
            "scheduled_date": "2026-06-01",
            "scheduled_time": "10:00",
        },
        format="json",
    )
    assert r.status_code == 403


# ─── Session visibility ───────────────────────────────────────────────────────
def _session_ids(response):
    data = response.json()
    # Paginated: data may be {"count":..., "results":[...]} wrapped in envelope
    payload = data.get("data") or data
    if isinstance(payload, dict) and "results" in payload:
        return [s["id"] for s in payload["results"]]
    if isinstance(payload, list):
        return [s["id"] for s in payload]
    return []


@pytest.mark.django_db
def test_learner_sees_only_own_sessions(learner_client, learner2_client, session):
    """Learner sees their session; learner2 sees nothing (different learner)."""
    r1 = learner_client.get(SESSIONS_URL)
    assert r1.status_code == 200
    assert str(session.id) in _session_ids(r1)

    r2 = learner2_client.get(SESSIONS_URL)
    assert r2.status_code == 200
    assert str(session.id) not in _session_ids(r2)


@pytest.mark.django_db
def test_invigilator_sees_only_assigned_sessions(
    invigilator_client, invigilator_user2, session
):
    """Assigned invigilator sees the session; unassigned invigilator does not."""
    c2 = APIClient()
    c2.force_authenticate(user=invigilator_user2)

    r1 = invigilator_client.get(SESSIONS_URL)
    assert r1.status_code == 200
    assert str(session.id) in _session_ids(r1)

    r2 = c2.get(SESSIONS_URL)
    assert r2.status_code == 200
    assert str(session.id) not in _session_ids(r2)


@pytest.mark.django_db
def test_admin_sees_all_sessions(admin_client, session):
    """Admin → sees the session regardless of who it belongs to."""
    r = admin_client.get(SESSIONS_URL)
    assert r.status_code == 200
    assert str(session.id) in _session_ids(r)


# ─── Unauthenticated ─────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_unauthenticated_cannot_access_sessions(anon_client):
    """No token → 401 on sessions endpoint."""
    r = anon_client.get(SESSIONS_URL)
    assert r.status_code == 401


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_unauthenticated_cannot_validate_pin(anon_client, session):
    """No token → 401 on validate-pin."""
    r = anon_client.post(
        VALIDATE_PIN_URL,
        {"session_id": str(session.id), "pin": "123456"},
        format="json",
    )
    assert r.status_code == 401


# ─── validate-pin learner-only ────────────────────────────────────────────────
@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_admin_cannot_validate_pin(admin_client, session):
    """Admin → 403 on validate-pin (learner-only)."""
    r = admin_client.post(
        VALIDATE_PIN_URL,
        {"session_id": str(session.id), "pin": "123456"},
        format="json",
    )
    assert r.status_code == 403


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_invigilator_cannot_validate_pin(invigilator_client, session):
    """Invigilator → 403 on validate-pin."""
    r = invigilator_client.post(
        VALIDATE_PIN_URL,
        {"session_id": str(session.id), "pin": "123456"},
        format="json",
    )
    assert r.status_code == 403


# ─── Resit: invigilator/admin only ───────────────────────────────────────────
@pytest.mark.django_db
def test_learner_cannot_create_resit(learner_client):
    """Learner → 403 on POST /exams/retakes/resit/."""
    r = learner_client.post(
        RESIT_URL,
        {"previous_result_id": "00000000-0000-0000-0000-000000000000",
         "invigilator_id": "00000000-0000-0000-0000-000000000001"},
        format="json",
    )
    assert r.status_code == 403


# ─── Results scoping ──────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_learner_sees_only_own_results(learner_client, learner2_client, in_progress_session):
    """Learner1's result is invisible to learner2."""
    from apps.exams.models import ExamResult

    sess = in_progress_session
    result = ExamResult.objects.create(
        session=sess,
        learner=sess.learner,
        exam_config=sess.exam_config,
        qualification=sess.exam_config.qualification,
        score_percent=80,
        correct_count=4,
        total_questions=5,
        grade="merit",
        passed=True,
        time_taken_seconds=1800,
        exam_date=sess.scheduled_date,
    )

    def result_ids(response):
        payload = response.json().get("data") or response.json()
        if isinstance(payload, dict) and "results" in payload:
            return [r["id"] for r in payload["results"]]
        return []

    r1 = learner_client.get(RESULTS_URL)
    assert r1.status_code == 200
    assert str(result.id) in result_ids(r1)

    r2 = learner2_client.get(RESULTS_URL)
    assert r2.status_code == 200
    assert str(result.id) not in result_ids(r2)


# ─── Retake approve/deny admin only ──────────────────────────────────────────
@pytest.mark.django_db
def test_learner_cannot_approve_retake(learner_client):
    """Learner → 403 on approve endpoint."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = learner_client.put(f"/exams/retakes/{fake_id}/approve/", {}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_invigilator_cannot_approve_retake(invigilator_client):
    """Invigilator → 403 on approve endpoint."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = invigilator_client.put(f"/exams/retakes/{fake_id}/approve/", {}, format="json")
    assert r.status_code == 403
