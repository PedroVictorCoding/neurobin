import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ClinicalDocument, ClinicalProfile, ClinicalProfileDraftValue


class RestrictedClinicalProfileTests(TestCase):
    def setUp(self):
        self.private_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.private_dir.cleanup)
        self.override = override_settings(
            METABOLIC_ASSESSMENT_ENABLED=True,
            CLINICAL_DOCUMENT_ROOT=self.private_dir.name,
            CLINICAL_DOCUMENT_KEYS='test:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=',
            CLINICAL_DOCUMENT_ACTIVE_KEY='test',
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.owner = User.objects.create_user('clinical-owner', is_staff=True)
        self.other = User.objects.create_user('clinical-other', is_staff=True)
        self.profile = ClinicalProfile.objects.create(
            user=self.owner, consent_version='v1', consented_at=timezone.now(), egfr=82,
        )

    def test_profile_api_is_private(self):
        client = APIClient()
        client.force_authenticate(self.other)
        response = client.get('/api/accounts/clinical-profile/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['profile'])

    def test_confirmed_document_value_updates_profile_but_requires_reverification(self):
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-test'),
            sha256='b' * 64, content_type='application/pdf', status='review', encryption_key_version='test',
        )
        draft = ClinicalProfileDraftValue.objects.create(
            document=document, field_name='egfr', value='55', provenance={'page': 1},
        )
        self.profile.verified_at = timezone.now()
        self.profile.save(update_fields=['verified_at'])
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.post(f'/api/accounts/clinical-document/{document.id}/confirm/', {'draft_id': draft.id})
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(float(self.profile.egfr), 55.0)
        self.assertIsNone(self.profile.verified_at)
        self.assertEqual(self.profile.provenance['egfr']['document_id'], document.id)

    def test_delete_removes_restricted_profile(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.delete('/api/accounts/clinical-profile/1/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ClinicalProfile.objects.filter(user=self.owner).exists())

    def test_upload_rejects_mismatched_file_signature(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        upload = SimpleUploadedFile('fake.pdf', b'not-a-pdf', content_type='application/pdf')
        response = client.post('/api/accounts/clinical-document/', {'file': upload}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ClinicalDocument.objects.filter(user=self.owner).exists())
