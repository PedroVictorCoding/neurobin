import io
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ClinicalAuditEvent, ClinicalProfileDraftValue


def audit(document, event_type, *, user=None, metadata=None):
    return ClinicalAuditEvent.objects.create(
        document=document, user=user, event_type=event_type, metadata=metadata or {},
    )


def extract_document(document):
    if document.status != 'clean':
        raise ValidationError('Only clean documents may be extracted.')
    document.status = 'extraction_pending'
    document.save(update_fields=['status'])
    with document.file.open('rb') as handle:
        raw = handle.read()
    if document.content_type == 'application/pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        pages = [(index + 1, page.extract_text() or '') for index, page in enumerate(reader.pages)]
    else:
        import pytesseract
        from PIL import Image
        pages = [(1, pytesseract.image_to_string(Image.open(io.BytesIO(raw))))]
    text = '\n'.join(value for _, value in pages)
    patterns = {
        'egfr': r'(?i)\beGFR\D{0,20}(\d{1,3}(?:\.\d+)?)',
        'weight_kg': r'(?i)\bweight\D{0,12}(\d{2,3}(?:\.\d+)?)\s*kg',
        'height_cm': r'(?i)\bheight\D{0,12}(\d{2,3}(?:\.\d+)?)\s*cm',
        'child_pugh_class': r'(?i)child[- ]pugh\D{0,12}([ABC])\b',
    }
    for field_name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            page = next((number for number, value in pages if match.group(0) in value), 1)
            ClinicalProfileDraftValue.objects.update_or_create(
                document=document, field_name=field_name,
                defaults={'value': match.group(1), 'provenance': {
                    'page': page, 'matched_text': match.group(0), 'extractor': 'rules-v1',
                }},
            )
    now = timezone.now()
    document.extracted_text = text
    document.status = 'review'
    document.extraction_completed_at = now
    document.purge_after = now + timedelta(days=settings.CLINICAL_DOCUMENT_RETENTION_DAYS)
    document.save(update_fields=['extracted_text', 'status', 'extraction_completed_at', 'purge_after'])
    audit(document, 'extraction_completed', metadata={'draft_count': document.draft_values.count()})


def purge_document(document, *, reason='retention'):
    if document.file:
        document.file.delete(save=False)
    document.file = ''
    document.extracted_text = ''
    document.status = 'purged'
    document.purged_at = timezone.now()
    document.save(update_fields=['file', 'extracted_text', 'status', 'purged_at'])
    audit(document, 'purged', metadata={'reason': reason})
