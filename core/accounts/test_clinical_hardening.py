import os
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.clinical_services import purge_document
from accounts.models import ClinicalAuditEvent, ClinicalDocument
from accounts.tasks import scan_clinical_document


KEYS = 'test:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY='


class ClinicalDocumentHardeningTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(
            METABOLIC_ASSESSMENT_ENABLED=True, CLINICAL_DOCUMENT_ROOT=self.temp.name,
            CLINICAL_DOCUMENT_KEYS=KEYS, CLINICAL_DOCUMENT_ACTIVE_KEY='test',
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.owner = User.objects.create_user('hardening-owner', is_staff=True)
        self.other = User.objects.create_user('hardening-other', is_staff=True)

    @patch('accounts.clinical_api.scan_clinical_document.delay')
    def test_upload_is_encrypted_quarantined_and_has_no_url(self, delay):
        client = APIClient(); client.force_authenticate(self.owner)
        upload = SimpleUploadedFile('report.pdf', b'%PDF-1.4 sensitive value', content_type='application/pdf')
        response = client.post('/api/accounts/clinical-document/', {'file': upload}, format='multipart')
        self.assertEqual(response.status_code, 201)
        document = ClinicalDocument.objects.get(user=self.owner)
        self.assertEqual(document.status, 'quarantined')
        stored = Path(document.file.path).read_bytes()
        self.assertNotIn(b'sensitive value', stored)
        self.assertEqual(os.stat(document.file.path).st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            _ = document.file.url
        delay.assert_called_once_with(document.id)
        self.assertTrue(ClinicalAuditEvent.objects.filter(document=document, event_type='uploaded').exists())

    def test_cross_user_download_is_not_found(self):
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-clean'),
            sha256='d' * 64, content_type='application/pdf', status='review',
            encryption_key_version='test', scanned_at=timezone.now(),
        )
        client = APIClient(); client.force_authenticate(self.other)
        self.assertEqual(client.get(f'/api/accounts/clinical-document/{document.id}/download/').status_code, 404)

    def test_ciphertext_tampering_fails_authentication(self):
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-clean'),
            sha256='e' * 64, content_type='application/pdf', encryption_key_version='test',
        )
        path = Path(document.file.path)
        payload = bytearray(path.read_bytes()); payload[-1] ^= 1; path.write_bytes(payload)
        with self.assertRaises(Exception):
            document.file.open('rb')

    @patch('accounts.tasks.extract_document')
    @patch('clamd.ClamdUnixSocket')
    def test_clean_scan_allows_extraction(self, client_class, extract):
        client_class.return_value.instream.return_value = {'stream': ('OK', None)}
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-clean'),
            sha256='1' * 64, content_type='application/pdf', encryption_key_version='test',
        )
        self.assertEqual(scan_clinical_document.run(document.id), 'review')
        document.refresh_from_db()
        self.assertEqual(document.status, 'clean')
        extract.assert_called_once_with(document)

    @patch('clamd.ClamdUnixSocket')
    def test_infected_scan_deletes_quarantined_file(self, client_class):
        client_class.return_value.instream.return_value = {'stream': ('FOUND', 'Eicar-Test-Signature')}
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-infected'),
            sha256='2' * 64, content_type='application/pdf', encryption_key_version='test',
        )
        path = document.file.path
        self.assertEqual(scan_clinical_document.run(document.id), 'infected')
        document.refresh_from_db()
        self.assertEqual(document.status, 'infected')
        self.assertFalse(Path(path).exists())

    def test_previous_key_remains_readable_during_rotation(self):
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-old-key'),
            sha256='3' * 64, content_type='application/pdf', encryption_key_version='test',
        )
        rotated = KEYS + ',next:YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk='
        with override_settings(CLINICAL_DOCUMENT_KEYS=rotated, CLINICAL_DOCUMENT_ACTIVE_KEY='next'):
            with document.file.open('rb') as handle:
                self.assertEqual(handle.read(), b'%PDF-old-key')

    def test_purge_removes_file_but_retains_audit(self):
        document = ClinicalDocument.objects.create(
            user=self.owner, file=SimpleUploadedFile('report.pdf', b'%PDF-clean'),
            sha256='f' * 64, content_type='application/pdf', status='confirmed',
            encryption_key_version='test', purge_after=timezone.now() - timedelta(days=1),
        )
        path = document.file.path
        purge_document(document)
        document.refresh_from_db()
        self.assertEqual(document.status, 'purged')
        self.assertFalse(Path(path).exists())
        self.assertTrue(ClinicalAuditEvent.objects.filter(document=document, event_type='purged').exists())

    @override_settings(METABOLIC_ASSESSMENT_ENABLED=False)
    def test_feature_disabled_is_hidden(self):
        client = APIClient(); client.force_authenticate(self.owner)
        self.assertEqual(client.get('/api/accounts/clinical-profile/').status_code, 404)

    def test_staff_portal_template_loads(self):
        client = APIClient(); client.force_login(self.owner)
        response = client.get('/accounts/profile/clinical/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Research use only')
        self.assertContains(response, 'Pharmacogenomics (PGx)')

    def test_audit_events_are_immutable(self):
        event = ClinicalAuditEvent.objects.create(user=self.owner, event_type='viewed')
        event.metadata = {'changed': True}
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()
