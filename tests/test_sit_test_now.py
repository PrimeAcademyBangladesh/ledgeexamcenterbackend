"""
test_sit_test_now.py
====================
Covers the "Sit Test Now" (allow-immediate-start) action being opened up to
invigilators (previously admin-only), per the client's request to surface a
"Sit Test Now" option on the invigilator dashboard / scheduled-exam details
as well as the admin exam-session view.

Row-level access is enforced by ExamSessionViewSet.get_queryset(): an
invigilator can only act on sessions assigned to them.
"""
import pytest
from rest_framework.test import APIClient

URL = "/exams/sessions/{}/allow-immediate-start/"


def sit_now(client, session):
    return client.post(URL.format(session.id), {}, format="json")


@pytest.mark.django_db
def test_admin_can_trigger_sit_now(admin_client, session):
    assert session.allow_immediate_start is False
    r = sit_now(admin_client, session)
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.allow_immediate_start is True


@pytest.mark.django_db
def test_assigned_invigilator_can_trigger_sit_now(invigilator_client, invigilator_user, session):
    assert session.invigilator == invigilator_user
    r = sit_now(invigilator_client, session)
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.allow_immediate_start is True


@pytest.mark.django_db
def test_unassigned_invigilator_cannot_trigger_sit_now(invigilator_user2, session):
    other_client = APIClient()
    other_client.force_authenticate(user=invigilator_user2)
    assert session.invigilator != invigilator_user2

    r = sit_now(other_client, session)
    assert r.status_code == 404  # row-level filtering hides sessions not assigned to them
    session.refresh_from_db()
    assert session.allow_immediate_start is False


@pytest.mark.django_db
def test_learner_cannot_trigger_sit_now(learner_client, session):
    r = sit_now(learner_client, session)
    assert r.status_code == 403
    session.refresh_from_db()
    assert session.allow_immediate_start is False


@pytest.mark.django_db
def test_sit_now_rejected_for_non_scheduled_session(invigilator_client, session):
    session.status = "in_progress"
    session.save(update_fields=["status"])

    r = sit_now(invigilator_client, session)
    assert r.status_code == 400
    session.refresh_from_db()
    assert session.allow_immediate_start is False
