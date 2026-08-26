import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from compounds.models import Compound, MetabolicInteractionEvidence, MetabolicReferenceCase, MetabolicValidationRun


class MetabolicValidationGateTests(TestCase):
    def setUp(self):
        self.perpetrator = Compound.objects.create(name='Validated Inhibitor')
        self.victim = Compound.objects.create(name='Validated Substrate')
        self.negative_perpetrator = Compound.objects.create(name='Non-interacting Control A')
        self.negative_victim = Compound.objects.create(name='Non-interacting Control B')
        now = timezone.now()
        for compound, role, strength in [
            (self.perpetrator, 'inhibitor', 'strong'), (self.victim, 'substrate', 'sensitive'),
        ]:
            MetabolicInteractionEvidence.objects.create(
                compound=compound, enzyme='CYP3A4', role=role, strength=strength,
                evidence_tier='label_clinical', source='fda', source_record_id=role,
                source_version='v1', source_checksum='a' * 64, retrieved_at=now,
            )

    def test_metrics_and_pharmacist_signature_gate_release(self):
        MetabolicReferenceCase.objects.create(
            dataset_version='gold-v1', perpetrator=self.perpetrator, victim=self.victim,
            expected_tier='high', expected_mechanism='inhibitor_to_substrate', rationale='Known pair',
            sources=['FDA'], reviewed_by_name='Clinical Pharmacist', pharmacist_approved_at=timezone.now(),
        )
        MetabolicReferenceCase.objects.create(
            dataset_version='gold-v1', perpetrator=self.negative_perpetrator,
            victim=self.negative_victim, expected_tier='unknown',
            expected_mechanism='none', rationale='Negative control', sources=['review'],
            reviewed_by_name='Clinical Pharmacist', pharmacist_approved_at=timezone.now(),
        )
        out = StringIO()
        call_command('validate_metabolic_reference_set', dataset_version='gold-v1', json=True, stdout=out)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload['passed_metrics'])
        self.assertTrue(payload['pharmacist_signed_off'])
        self.assertTrue(payload['release_ready'])
        self.assertTrue(MetabolicValidationRun.objects.get().passed_metrics)
