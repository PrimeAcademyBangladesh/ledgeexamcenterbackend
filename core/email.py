from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def build_set_password_url(user) -> str:
    """
    Build a "set/reset your password" link using the same uid + token scheme
    as the forgot-password flow (see apps.users.views.ForgotPasswordView), so
    welcome emails can reuse the existing /reset-password page — no separate
    "first login" page is needed.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = PasswordResetTokenGenerator().make_token(user)
    return f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"


def send_email(subject: str, to_email: str, template_name: str, context: dict) -> None:
    """
    Send an HTML + plain-text email using templates from templates/emails/.

    Args:
        subject:       Email subject line.
        to_email:      Recipient address.
        template_name: Base name of the template (e.g. "password_reset" loads
                       emails/password_reset.html and emails/password_reset.txt).
        context:       Template context variables.
    """
    context.setdefault("year", timezone.now().year)
    text_body = render_to_string(f"emails/{template_name}.txt", context)
    html_body = render_to_string(f"emails/{template_name}.html", context)
    msg = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [to_email])
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)
