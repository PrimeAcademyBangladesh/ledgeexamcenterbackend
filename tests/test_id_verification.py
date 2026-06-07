"""
test_id_verification.py
=======================
Covers the "ID confirmed" lock rules raised by the client:

  - An invigilator can freely tick/untick id_verified while a session is
    still "scheduled".
  - Once the exam has actually started (status moves past "scheduled" —
    e.g. via PIN entry or the unlock action), id_verified becomes locked
    and can no longer be changed (previously it could be un-ticked mid-exam).
"""
import pytest
from freezegun import freeze_time

from .conftest import INSIDE_WINDOW

VERIFY_URL = "/exams/sessions/{}/verify-id/"
UNLOCK_URL = "/exams/sessions/{}/unlock/"


def verify_id(client, session, value=True):
    return client.patch(VERIFY_URL.format(session.id), {"id_verified": value}, format="json")


@pytest.mark.django_db
def test_invigilator_can_toggle_id_verified_while_scheduled(invigilator_client, session):
    assert session.status == "scheduled"

    r = verify_id(invigilator_client, session, False)
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.id_verified is False

    r = verify_id(invigilator_client, session, True)
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.id_verified is True


@pytest.mark.django_db
def test_id_verified_locked_once_session_in_progress(invigilator_client, session):
    session.status = "in_progress"
    session.id_verified = True
    session.save(update_fields=["status", "id_verified"])

    r = verify_id(invigilator_client, session, False)
    assert r.status_code == 400
    assert r.json()["success"] is False

    session.refresh_from_db()
    assert session.id_verified is True  # unchanged — cannot be un-ticked mid-exam


@pytest.mark.django_db
def test_id_verified_locked_once_session_completed(invigilator_client, session):
    session.status = "completed"
    session.id_verified = True
    session.save(update_fields=["status", "id_verified"])

    r = verify_id(invigilator_client, session, False)
    assert r.status_code == 400

    session.refresh_from_db()
    assert session.id_verified is True


@pytest.mark.django_db
@freeze_time(INSIDE_WINDOW)
def test_unlock_moves_session_to_in_progress_and_locks_id_verified(invigilator_client, session):
    """unlock() requires id_verified=True and flips status to in_progress —
    after that, verify-id must be locked (the client's "ID confirmed should
    move to locked when the test is unlocked" requirement)."""
    assert session.id_verified is True
    assert session.status == "scheduled"

    r = invigilator_client.post(UNLOCK_URL.format(session.id), {}, format="json")
    assert r.status_code == 200
    session.refresh_from_db()
    assert session.status == "in_progress"

    r = verify_id(invigilator_client, session, False)
    assert r.status_code == 400
    session.refresh_from_db()
    assert session.id_verified is True
