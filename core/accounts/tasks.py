from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .clinical_services import audit, extract_document, purge_document
from .models import ClinicalDocument


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def scan_clinical_document(self, document_id):
    document = ClinicalDocument.objects.get(pk=document_id)
    if document.status != 'quarantined':
        return document.status
    document.status = 'scanning'
    document.save(update_fields=['status'])
    audit(document, 'scan_started')
    try:
        import clamd
        client = clamd.ClamdUnixSocket(path=settings.CLAMAV_UNIX_SOCKET)
        with document.file.open('rb') as handle:
            result = client.instream(handle)
        verdict, signature = result.get('stream', ('ERROR', 'missing verdict'))
        document.scanned_at = timezone.now()
        document.scan_signature = signature or ''
        if verdict == 'FOUND':
            document.status = 'infected'
            document.save(update_fields=['status', 'scanned_at', 'scan_signature'])
            audit(document, 'scan_infected', metadata={'signature': signature})
            document.file.delete(save=False)
            return 'infected'
        if verdict != 'OK':
            raise RuntimeError(f'Unexpected ClamAV verdict: {verdict}')
        document.status = 'clean'
        document.save(update_fields=['status', 'scanned_at', 'scan_signature'])
        audit(document, 'scan_clean')
        extract_document(document)
        return 'review'
    except Exception as exc:
        document.status = 'quarantined'
        document.extraction_error = str(exc)
        document.save(update_fields=['status', 'extraction_error'])
        audit(document, 'scan_failed', metadata={'error': str(exc)[:500]})
        raise self.retry(exc=exc)


@shared_task
def purge_expired_clinical_documents():
    count = 0
    for document in ClinicalDocument.objects.filter(
        purge_after__lte=timezone.now(), purged_at__isnull=True,
    ).exclude(status__in=['infected', 'purged']):
        purge_document(document)
        count += 1
    return count
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
