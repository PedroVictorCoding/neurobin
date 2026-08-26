import json
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from compounds.models import MetabolicReferenceCase, MetabolicValidationRun
from stacks.metabolic import assess_metabolic_interaction


class Command(BaseCommand):
    help = 'Evaluate a pharmacist-reviewed metabolic reference set and persist release metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--dataset-version', required=True)
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        cases = list(MetabolicReferenceCase.objects.filter(dataset_version=options['dataset_version']))
        if not cases:
            raise CommandError('Reference set is empty.')
        matrix = {expected: {predicted: 0 for predicted in ['high', 'moderate', 'hypothesis', 'unknown']}
                  for expected in ['high', 'moderate', 'hypothesis', 'unknown']}
        predictions = []
        for case in cases:
            items = [
                SimpleNamespace(compound_id=case.perpetrator_id, dosage_amount=None, dosage_unit='mg', intake_time=None),
                SimpleNamespace(compound_id=case.victim_id, dosage_amount=None, dosage_unit='mg', intake_time=None),
            ]
            result = assess_metabolic_interaction(items)
            predicted = result['tier']
            matrix[case.expected_tier][predicted] += 1
            predictions.append((case.expected_tier, predicted))
        high_cases = [row for row in predictions if row[0] == 'high']
        non_high = [row for row in predictions if row[0] != 'high']
        sensitivity = sum(row[1] == 'high' for row in high_cases) / len(high_cases) if high_cases else 0.0
        specificity = sum(row[1] != 'high' for row in non_high) / len(non_high) if non_high else 0.0
        coverage = sum(row[1] != 'unknown' for row in predictions) / len(predictions)
        promotions = sum(expected == 'hypothesis' and predicted not in {'hypothesis', 'unknown'} for expected, predicted in predictions)
        pharmacist_signed = all(case.pharmacist_approved_at and case.reviewed_by_name for case in cases)
        passed = sensitivity >= .95 and specificity >= .90 and promotions == 0
        run = MetabolicValidationRun.objects.create(
            dataset_version=options['dataset_version'], model_version='metabolic-interaction-v4',
            case_count=len(cases), high_risk_sensitivity=sensitivity, specificity=specificity,
            coverage=coverage, prediction_promotions=promotions, confusion_matrix=matrix,
            passed_metrics=passed, pharmacist_signed_off=pharmacist_signed,
        )
        payload = {'run_id': run.id, 'sensitivity': sensitivity, 'specificity': specificity,
                   'coverage': coverage, 'prediction_promotions': promotions,
                   'passed_metrics': passed, 'pharmacist_signed_off': pharmacist_signed,
                   'release_ready': passed and pharmacist_signed, 'confusion_matrix': matrix}
        self.stdout.write(json.dumps(payload, sort_keys=True))
