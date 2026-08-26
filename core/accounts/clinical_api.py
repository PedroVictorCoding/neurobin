import hashlib
import os
from pathlib import Path
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import ClinicalDocument, ClinicalProfile, ClinicalProfileDraftValue, PharmacogenomicResult
from .clinical_feature import MetabolicFeaturePermission
from .clinical_services import audit, purge_document
from .private_storage import active_key_version
from .tasks import scan_clinical_document


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
        fields = [
            'id', 'file', 'sha256', 'content_type', 'status', 'scan_signature', 'scanned_at',
            'encryption_key_version', 'extraction_error', 'extraction_completed_at',
            'purge_after', 'purged_at', 'created_at', 'draft_values',
        ]
        read_only_fields = ['sha256', 'content_type', 'status', 'extraction_error', 'created_at']
        extra_kwargs = {'file': {'write_only': True}}

    def get_draft_values(self, obj):
        return list(obj.draft_values.values('id', 'field_name', 'value', 'provenance', 'confirmed_at', 'rejected_at'))


class ClinicalProfileViewSet(viewsets.ViewSet):
    permission_classes = [MetabolicFeaturePermission]

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

    @action(detail=False, methods=['get'])
    def readiness(self, request):
        from django.conf import settings
        from compounds.models import MetabolicSourceSnapshot, MetabolicValidationRun
        checks = {}
        try:
            checks['encryption_key'] = {'ok': bool(active_key_version())}
        except Exception as exc:
            checks['encryption_key'] = {'ok': False, 'detail': str(exc)}
        try:
            root = Path(settings.CLINICAL_DOCUMENT_ROOT).resolve()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            checks['private_storage'] = {'ok': root != Path(settings.MEDIA_ROOT).resolve() and os.access(root, os.W_OK)}
        except Exception as exc:
            checks['private_storage'] = {'ok': False, 'detail': str(exc)}
        try:
            import clamd
            checks['clamav'] = {'ok': clamd.ClamdUnixSocket(path=settings.CLAMAV_UNIX_SOCKET).ping() == 'PONG'}
        except Exception as exc:
            checks['clamav'] = {'ok': False, 'detail': str(exc)}
        snapshot = MetabolicSourceSnapshot.objects.order_by('-retrieved_at').first()
        checks['source_snapshot'] = {'ok': bool(snapshot), 'retrieved_at': snapshot.retrieved_at if snapshot else None}
        validation = MetabolicValidationRun.objects.order_by('-created_at').first()
        checks['clinical_gate'] = {'ok': bool(validation and validation.passed_metrics and validation.pharmacist_signed_off)}
        ready = all(row['ok'] for row in checks.values())
        return Response({'ready': ready, 'checks': checks}, status=200 if ready else 503)


class ClinicalDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = ClinicalDocumentSerializer
    permission_classes = [MetabolicFeaturePermission]

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
        document = serializer.save(
            user=self.request.user, sha256=digest, content_type=content_type,
            status='quarantined', encryption_key_version=active_key_version(),
        )
        audit(document, 'uploaded', user=self.request.user, metadata={'content_type': content_type, 'size': len(raw)})
        try:
            scan_clinical_document.delay(document.id)
        except Exception as exc:
            purge_document(document, reason='queue_failure')
            raise serializers.ValidationError('Document scanning is unavailable; upload was discarded.') from exc

    def perform_destroy(self, instance):
        audit(instance, 'deleted', user=self.request.user)
        purge_document(instance, reason='user_delete')

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        document = self.get_object()
        if document.status not in {'clean', 'review', 'confirmed'} or not document.scanned_at or not document.file:
            return Response({'detail': 'Document is not available after a clean scan.'}, status=409)
        audit(document, 'downloaded', user=request.user)
        return FileResponse(document.file.open('rb'), content_type=document.content_type, as_attachment=True,
                            filename=f'clinical-document-{document.id}')

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
        audit(document, 'draft_confirmed', user=request.user, metadata={'field_name': draft.field_name})
        return Response(ClinicalProfileSerializer(profile).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        document = self.get_object()
        draft = document.draft_values.filter(id=request.data.get('draft_id')).first()
        if not draft:
            return Response({'detail': 'Unknown draft value.'}, status=400)
        draft.rejected_at = timezone.now()
        draft.save(update_fields=['rejected_at'])
        audit(document, 'draft_rejected', user=request.user, metadata={'field_name': draft.field_name})
        return Response({'draft_id': draft.id, 'rejected': True})
