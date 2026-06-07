"""
test_welcome_emails.py
======================
Covers the client's ask: when a learner or invigilator account is created,
they should receive a welcome email containing a link to the website, their
username, and a way to set their password.

Templates (learner_welcome / invigilator_welcome) previously didn't exist —
send_email() failed silently for learners and invigilators got nothing at
all (a literal `# TODO` in RegisterInvigilatorSerializer.create()).

Uses the locmem email backend (via the `settings` fixture) so messages land
in django.core.mail.outbox instead of the console backend configured for dev.
"""
import pytest
from django.urls import reverse

from apps.invigilators.models import ProviderCentre
from apps.users.models import User


@pytest.fixture(autouse=True)
def locmem_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


# ─── Resend welcome (learner) ────────────────────────────────────────────────
@pytest.mark.django_db
def test_resend_learner_welcome_contains_username_and_set_password_link(
    admin_client, learner_user, mailoutbox
):
    url = reverse("learner-resend-welcome", kwargs={"user_id": learner_user.id})
    r = admin_client.post(url)
    assert r.status_code == 200
    assert len(mailoutbox) == 1

    msg = mailoutbox[0]
    assert msg.to == [learner_user.email]
    assert "Welcome" in msg.subject

    html_body = msg.alternatives[0][0]
    for body in (msg.body, html_body):
        assert learner_user.email in body              # username == email
        assert "/reset-password?uid=" in body          # set-password link
        assert "token=" in body


# ─── Resend welcome (invigilator) ────────────────────────────────────────────
@pytest.mark.django_db
def test_resend_invigilator_welcome_contains_username_and_set_password_link(
    admin_client, invigilator_user, mailoutbox
):
    url = reverse("invigilator-resend-welcome", kwargs={"pk": invigilator_user.id})
    r = admin_client.post(url)
    assert r.status_code == 200
    assert len(mailoutbox) == 1

    msg = mailoutbox[0]
    assert msg.to == [invigilator_user.email]

    html_body = msg.alternatives[0][0]
    for body in (msg.body, html_body):
        assert invigilator_user.email in body
        assert "/reset-password?uid=" in body
        assert "token=" in body


# ─── Registration triggers the welcome email ────────────────────────────────
@pytest.mark.django_db
def test_invigilator_registration_sends_welcome_email(admin_client, mailoutbox):
    """RegisterInvigilatorSerializer.create() previously had a bare `# TODO`
    and sent nothing at all."""
    provider = ProviderCentre.objects.create(name="Test Centre", code="TST001")

    r = admin_client.post(
        reverse("invigilator-list"),
        {
            "firstName": "New",
            "lastName": "Invigilator",
            "email": "new-invigilator@example.com",
            "providerCode": provider.code,
            "password": "Welcome123!",
        },
        format="json",
    )
    assert r.status_code in (200, 201)
    assert len(mailoutbox) == 1

    msg = mailoutbox[0]
    new_user = User.objects.get(email="new-invigilator@example.com")
    assert msg.to == [new_user.email]
    assert "/reset-password?uid=" in msg.body


@pytest.mark.django_db
def test_invigilator_registration_succeeds_even_if_email_send_fails(admin_client, monkeypatch):
    """Mirrors the learner path's `except Exception: pass` — a transient SMTP
    failure must not block account creation."""
    provider = ProviderCentre.objects.create(name="Test Centre", code="TST002")

    def boom(*args, **kwargs):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr("apps.invigilators.serializers.send_email", boom)

    r = admin_client.post(
        reverse("invigilator-list"),
        {
            "firstName": "Resilient",
            "lastName": "Invigilator",
            "email": "resilient-invigilator@example.com",
            "providerCode": provider.code,
            "password": "Welcome123!",
        },
        format="json",
    )
    assert r.status_code in (200, 201)
    assert User.objects.filter(email="resilient-invigilator@example.com").exists()
