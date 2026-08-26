import json
import tempfile

from django.test import TestCase

from compounds.metabolic_import import import_metabolic_source
from compounds.models import Compound, MetabolicImportReview, MetabolicInteractionEvidence


class MetabolicImportTests(TestCase):
    def setUp(self):
        self.compound = Compound.objects.create(name='Matched Drug', inchi_key='TEST-INCHI-KEY')

    def source_file(self, records):
        handle = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(records, handle)
        handle.close()
        self.addCleanup(lambda: __import__('os').unlink(handle.name))
        return handle.name

    def test_import_is_idempotent_and_normalizes_role(self):
        path = self.source_file([{
            'id': 'fda-1', 'compound': 'Matched Drug', 'inchi_key': 'TEST-INCHI-KEY',
            'enzyme': 'cyp3a4', 'role': 'reversible inhibitor', 'strength': 'strong',
        }])
        first = import_metabolic_source(source='fda', source_version='v1', location=path, evidence_tier='label_clinical')
        second = import_metabolic_source(source='fda', source_version='v1', location=path, evidence_tier='label_clinical')
        self.assertEqual(first['created'], 1)
        self.assertEqual(second['updated'], 1)
        self.assertEqual(MetabolicInteractionEvidence.objects.count(), 1)
        self.assertEqual(MetabolicInteractionEvidence.objects.get().role, 'inhibitor')

    def test_unmatched_record_enters_review_queue(self):
        path = self.source_file([{'id': 'fda-2', 'compound': 'Unknown Drug', 'enzyme': 'CYP2D6', 'role': 'substrate'}])
        result = import_metabolic_source(source='fda', source_version='v1', location=path, evidence_tier='label_clinical')
        self.assertEqual(result['review'], 1)
        self.assertEqual(MetabolicImportReview.objects.get().reason, 'ambiguous_or_unmatched')

    def test_dry_run_does_not_write(self):
        path = self.source_file([{'id': 'fda-3', 'compound': 'Matched Drug', 'enzyme': 'CYP2D6', 'role': 'substrate'}])
        result = import_metabolic_source(source='fda', source_version='v1', location=path, evidence_tier='label_clinical', dry_run=True)
        self.assertEqual(result['created'], 1)
        self.assertFalse(MetabolicInteractionEvidence.objects.exists())
