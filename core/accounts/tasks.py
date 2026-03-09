from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_transactional_email_task(
    self,
    *,
    subject: str,
    body_text: str,
    recipient_list: list[str],
    body_html: str = "",
    from_email: str = "",
):
    effective_from = from_email or settings.DEFAULT_FROM_EMAIL
    message = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=effective_from,
        to=list(recipient_list),
    )
    if body_html:
        message.attach_alternative(body_html, "text/html")
    return message.send()
