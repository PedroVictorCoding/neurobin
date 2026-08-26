from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ClinicalProfile
from compounds.models import Compound, MetabolicInteractionEvidence
from stacks.metabolic import assess_metabolic_interaction, build_pbpk_export
from stacks.models import Stack, StackItem


class MetabolicInteractionV4Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('metabolic-user')
        self.inhibitor = Compound.objects.create(name='Documented Inhibitor')
        self.substrate = Compound.objects.create(name='Sensitive Substrate')
        self.stack = Stack.objects.create(user=self.user, name='Test Stack')
        self.inhibitor_item = StackItem.objects.create(stack=self.stack, compound=self.inhibitor, dosage_amount=10)
        self.substrate_item = StackItem.objects.create(stack=self.stack, compound=self.substrate, dosage_amount=5)

    def evidence(self, compound, role, strength, **extra):
        return MetabolicInteractionEvidence.objects.create(
            compound=compound, enzyme='CYP3A4', role=role, strength=strength,
            evidence_tier='label_clinical', source='fda', source_record_id=f'{compound.id}-{role}',
            source_version='2026-01', source_checksum='a' * 64, retrieved_at=timezone.now(), **extra,
        )

    def test_documented_strong_inhibitor_sensitive_substrate_is_high(self):
        self.evidence(self.inhibitor, 'inhibitor', 'strong')
        self.evidence(self.substrate, 'substrate', 'sensitive')
        result = assess_metabolic_interaction(self.stack.items.select_related('compound'))
        self.assertEqual(result['tier'], 'high')
        self.assertIsNone(result['findings'][0]['auc_ratio'])
        self.assertIn('substrate_fraction_metabolized', result['findings'][0]['missing_parameters'])

    def test_inducer_pair_is_mechanistic_and_moderate_when_not_sensitive(self):
        self.evidence(self.inhibitor, 'inducer', 'moderate')
        self.evidence(self.substrate, 'substrate', 'unknown')
        result = assess_metabolic_interaction(self.stack.items.select_related('compound'))
        self.assertEqual(result['tier'], 'moderate')
        self.assertEqual(result['findings'][0]['mechanism'], 'inducer_to_substrate')

    def test_same_cyp_predictions_are_hypothesis_only(self):
        result = assess_metabolic_interaction(self.stack.items.all(), predicted_compounds=[
            {'compound_id': self.inhibitor.id, 'name': self.inhibitor.name, 'cyp_endpoints': {'CYP3A4': .8}},
            {'compound_id': self.substrate.id, 'name': self.substrate.name, 'cyp_endpoints': {'CYP3A4': .7}},
        ])
        self.assertEqual(result['tier'], 'hypothesis')
        self.assertIsNone(result['findings'][0]['auc_ratio'])

    def test_pbpk_export_lists_missing_parameters(self):
        self.evidence(self.inhibitor, 'inhibitor', 'strong')
        self.evidence(self.substrate, 'substrate', 'sensitive')
        assessment = assess_metabolic_interaction(self.stack.items.select_related('compound'))
        export = build_pbpk_export(self.stack, assessment)
        self.assertEqual(export['status'], 'needs_data')
        self.assertIn('verified_clinical_profile', export['missing_parameters'])
        self.assertNotIn('auc_ratio', export)

    def test_equal_priority_contradictory_roles_are_unknown(self):
        self.evidence(self.inhibitor, 'inhibitor', 'strong')
        MetabolicInteractionEvidence.objects.create(
            compound=self.inhibitor, enzyme='CYP3A4', role='inducer', strength='strong',
            evidence_tier='label_clinical', source='dailymed', source_record_id='conflict',
            source_version='2026-01', source_checksum='c' * 64, retrieved_at=timezone.now(),
        )
        self.evidence(self.substrate, 'substrate', 'sensitive')
        result = assess_metabolic_interaction(self.stack.items.select_related('compound'))
        self.assertEqual(result['tier'], 'unknown')
        self.assertEqual(result['findings'][0]['mechanism'], 'contradictory_roles')

    def test_patient_context_endpoint_is_owner_only_and_not_in_public_cache(self):
        ClinicalProfile.objects.create(
            user=self.user, consent_version='v1', consented_at=timezone.now(),
            egfr=55, verified_at=timezone.now(),
        )
        owner_client = APIClient()
        owner_client.force_authenticate(self.user)
        response = owner_client.get(f'/api/stacks/stack/{self.stack.id}/metabolic_assessment/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['patient_context']['applied'])

        cached = self.stack.risk_assessment.details['metabolic_interaction_potential']
        self.assertFalse(cached['patient_context']['applied'])

        other = User.objects.create_user('metabolic-other')
        other_client = APIClient()
        other_client.force_authenticate(other)
        denied = other_client.get(f'/api/stacks/stack/{self.stack.id}/metabolic_assessment/')
        self.assertEqual(denied.status_code, 404)
