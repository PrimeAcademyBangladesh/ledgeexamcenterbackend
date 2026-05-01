from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone


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
