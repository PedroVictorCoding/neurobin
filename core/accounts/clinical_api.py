import hashlib
import io
import re

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ClinicalDocument, ClinicalProfile, ClinicalProfileDraftValue, PharmacogenomicResult


ALLOWED_CONTENT_TYPES = {'application/pdf', 'image/png', 'image/jpeg'}
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
CONFIRMABLE_FIELDS = {
    'date_of_birth', 'sex_at_birth', 'weight_kg', 'height_cm', 'pregnancy_status',
    'smoking_status', 'egfr', 'egfr_measured_at', 'child_pugh_class',
    'child_pugh_assessed_at', 'diagnoses',
}


class PharmacogenomicResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacogenomicResult
        exclude = ['profile']
        read_only_fields = ['verified_at']


class ClinicalProfileSerializer(serializers.ModelSerializer):
    pharmacogenomic_results = PharmacogenomicResultSerializer(many=True, read_only=True)

    class Meta:
        model = ClinicalProfile
        exclude = ['user']
        read_only_fields = ['created_at', 'updated_at', 'verified_at', 'revision']

    def validate(self, attrs):
        if attrs.get('egfr') is not None and not (0 <= attrs['egfr'] <= 250):
            raise serializers.ValidationError({'egfr': 'Expected 0–250 mL/min/1.73m².'})
        if attrs.get('child_pugh_class') and attrs['child_pugh_class'].upper() not in {'A', 'B', 'C'}:
            raise serializers.ValidationError({'child_pugh_class': 'Expected A, B, or C.'})
        return attrs


class ClinicalDocumentSerializer(serializers.ModelSerializer):
    draft_values = serializers.SerializerMethodField()

    class Meta:
        model = ClinicalDocument
        fields = ['id', 'file', 'sha256', 'content_type', 'status', 'extraction_error', 'created_at', 'draft_values']
        read_only_fields = ['sha256', 'content_type', 'status', 'extraction_error', 'created_at']
        extra_kwargs = {'file': {'write_only': True}}

    def get_draft_values(self, obj):
        return list(obj.draft_values.values('id', 'field_name', 'value', 'provenance', 'confirmed_at', 'rejected_at'))


def _extract_document(upload, content_type):
    raw = upload.read()
    upload.seek(0)
    if content_type == 'application/pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        pages = [(index + 1, page.extract_text() or '') for index, page in enumerate(reader.pages)]
    else:
        try:
            import pytesseract
            from PIL import Image
            pages = [(1, pytesseract.image_to_string(Image.open(io.BytesIO(raw))))]
        except Exception as exc:
            raise ValidationError(f'Image OCR unavailable: {exc}') from exc
    text = '\n'.join(value for _, value in pages)
    drafts = []
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
            drafts.append((field_name, match.group(1), {'page': page, 'matched_text': match.group(0), 'extractor': 'rules-v1'}))
    return text, drafts


class ClinicalProfileViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _get(self, request):
        return ClinicalProfile.objects.filter(user=request.user).first()

    def list(self, request):
        profile = self._get(request)
        return Response({'profile': ClinicalProfileSerializer(profile).data if profile else None})

    def create(self, request):
        serializer = ClinicalProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, created = ClinicalProfile.objects.update_or_create(
            user=request.user, defaults={**serializer.validated_data, 'revision': 1},
        )
        return Response(ClinicalProfileSerializer(profile).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def partial_update(self, request, pk=None):
        profile = self._get(request)
        if not profile:
            return Response({'detail': 'Clinical profile not found.'}, status=404)
        serializer = ClinicalProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(revision=profile.revision + 1, verified_at=None)
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        profile = self._get(request)
        if profile:
            profile.delete()
        return Response(status=204)

    @action(detail=False, methods=['post'])
    def verify(self, request):
        profile = self._get(request)
        if not profile:
            return Response({'detail': 'Clinical profile not found.'}, status=404)
        profile.verified_at = timezone.now()
        profile.revision += 1
        profile.save(update_fields=['verified_at', 'revision', 'updated_at'])
        return Response(ClinicalProfileSerializer(profile).data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        profile = self._get(request)
        return Response({'schema': 'neurobin-clinical-profile-v1', 'profile': ClinicalProfileSerializer(profile).data if profile else None})

    @action(detail=False, methods=['post'])
    def pgx(self, request):
        profile = self._get(request)
        if not profile:
            return Response({'detail': 'Clinical profile not found.'}, status=404)
        serializer = PharmacogenomicResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result, _created = PharmacogenomicResult.objects.update_or_create(
            profile=profile, gene=serializer.validated_data['gene'], defaults={
                **serializer.validated_data, 'verified_at': None,
            },
        )
        profile.verified_at = None
        profile.revision += 1
        profile.save(update_fields=['verified_at', 'revision', 'updated_at'])
        return Response(PharmacogenomicResultSerializer(result).data)


class ClinicalDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = ClinicalDocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ClinicalDocument.objects.filter(user=self.request.user).prefetch_related('draft_values')

    def perform_create(self, serializer):
        upload = self.request.FILES['file']
        content_type = upload.content_type or ''
        if content_type not in ALLOWED_CONTENT_TYPES or upload.size > MAX_DOCUMENT_BYTES:
            raise serializers.ValidationError('Only PDF, PNG, or JPEG files up to 10 MB are accepted.')
        raw = upload.read()
        valid_signature = (
            (content_type == 'application/pdf' and raw.startswith(b'%PDF-'))
            or (content_type == 'image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n'))
            or (content_type == 'image/jpeg' and raw.startswith(b'\xff\xd8\xff'))
        )
        if not valid_signature:
            raise serializers.ValidationError('The file signature does not match its declared type.')
        digest = hashlib.sha256(raw).hexdigest()
        upload.seek(0)
        document = serializer.save(user=self.request.user, sha256=digest, content_type=content_type)
        try:
            text, drafts = _extract_document(upload, content_type)
            document.extracted_text = text
            document.status = 'review'
            document.save(update_fields=['extracted_text', 'status'])
            for field_name, value, provenance in drafts:
                ClinicalProfileDraftValue.objects.update_or_create(
                    document=document, field_name=field_name,
                    defaults={'value': value, 'provenance': provenance},
                )
        except Exception as exc:
            document.status = 'failed'
            document.extraction_error = str(exc)
            document.save(update_fields=['status', 'extraction_error'])

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        document = self.get_object()
        draft = document.draft_values.filter(id=request.data.get('draft_id')).first()
        if not draft or draft.field_name not in CONFIRMABLE_FIELDS:
            return Response({'detail': 'Unknown or unsupported draft value.'}, status=400)
        profile = ClinicalProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response({'detail': 'Create a clinical profile before confirming values.'}, status=400)
        setattr(profile, draft.field_name, draft.value)
        profile.provenance[draft.field_name] = {'document_id': document.id, **draft.provenance}
        profile.revision += 1
        profile.verified_at = None
        profile.save()
        draft.confirmed_at = timezone.now()
        draft.save(update_fields=['confirmed_at'])
        if not document.draft_values.filter(confirmed_at__isnull=True, rejected_at__isnull=True).exists():
            document.status = 'confirmed'
            document.save(update_fields=['status'])
        return Response(ClinicalProfileSerializer(profile).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        document = self.get_object()
        draft = document.draft_values.filter(id=request.data.get('draft_id')).first()
        if not draft:
            return Response({'detail': 'Unknown draft value.'}, status=400)
        draft.rejected_at = timezone.now()
        draft.save(update_fields=['rejected_at'])
        return Response({'draft_id': draft.id, 'rejected': True})
