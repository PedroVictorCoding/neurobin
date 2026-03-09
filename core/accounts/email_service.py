from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import EmailVerificationToken

logger = logging.getLogger(__name__)


def _normalize_subject(raw: str) -> str:
    return " ".join((raw or "").split())


def _send_email(
    *,
    subject: str,
    body_text: str,
    recipients: Iterable[str],
    body_html: str = "",
    from_email: str = "",
):
    recipient_list = [email for email in recipients if email]
    if not recipient_list:
        return 0

    effective_from = from_email or settings.DEFAULT_FROM_EMAIL
    if getattr(settings, "EMAIL_DELIVERY_ASYNC", False):
        try:
            from .tasks import send_transactional_email_task

            send_transactional_email_task.delay(
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                recipient_list=recipient_list,
                from_email=effective_from,
            )
            return 1
        except Exception:
            logger.exception("Failed to enqueue transactional email; falling back to sync send.")

    message = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=effective_from,
        to=recipient_list,
    )
    if body_html:
        message.attach_alternative(body_html, "text/html")
    return message.send()


def _verification_expiry():
    ttl_hours = max(1, int(getattr(settings, "EMAIL_VERIFICATION_TOKEN_TTL_HOURS", 24)))
    return timezone.now() + timedelta(hours=ttl_hours)


def create_email_verification_token(user, *, purpose=EmailVerificationToken.PURPOSE_REGISTRATION, email: str | None = None):
    target_email = (email or user.email or "").strip().lower()
    EmailVerificationToken.objects.filter(
        user=user,
        purpose=purpose,
        email=target_email,
        used_at__isnull=True,
    ).delete()
    return EmailVerificationToken.objects.create(
        user=user,
        email=target_email,
        purpose=purpose,
        expires_at=_verification_expiry(),
    )


def send_registration_verification_email(request, user, token_obj: EmailVerificationToken):
    verify_url = request.build_absolute_uri(
        reverse("verify_email", kwargs={"token": token_obj.token})
    )
    ttl_hours = max(1, int(getattr(settings, "EMAIL_VERIFICATION_TOKEN_TTL_HOURS", 24)))
    context = {
        "user": user,
        "verify_url": verify_url,
        "compound_app_name": "Neurobin",
        "ttl_hours": ttl_hours,
    }

    subject = _normalize_subject(
        render_to_string("accounts/emails/verify_email_subject.txt", context)
    )
    body_text = render_to_string("accounts/emails/verify_email.txt", context)
    body_html = render_to_string("accounts/emails/verify_email.html", context)

    return _send_email(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        recipients=[token_obj.email],
    )


def issue_registration_verification(request, user):
    token_obj = create_email_verification_token(
        user,
        purpose=EmailVerificationToken.PURPOSE_REGISTRATION,
        email=user.email,
    )
    send_registration_verification_email(request, user, token_obj)
    return token_obj
