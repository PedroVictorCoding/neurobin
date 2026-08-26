import json
from unittest.mock import Mock

from django.test import TestCase, override_settings

from compounds.models import MetabolicImportReview, MetabolicSourceSnapshot
from compounds.source_adapters import fetch_fda_cyp_table, fetch_openfda_labels, queue_label_reviews, store_snapshot


KEYS = 'test:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY='


@override_settings(CLINICAL_DOCUMENT_KEYS=KEYS, CLINICAL_DOCUMENT_ACTIVE_KEY='test')
class OfficialSourceAdapterTests(TestCase):
    def response(self, *, content=b'', payload=None):
        response = Mock(status_code=200, content=content)
        response.raise_for_status.return_value = None
        if payload is not None:
            response.json.return_value = payload
        return response

    def test_fda_table_shape_is_normalized(self):
        html = b'''<table><tr><th>Drug or Other Substance</th><th>CYP Strg INH</th><th>CYP SENS SUB</th></tr>
        <tr><td>Example A</td><td>3A4 strong inhibitor</td><td></td></tr>
        <tr><td>Example B</td><td></td><td>2D6 sensitive substrate</td></tr></table>'''
        session = Mock(); session.get.return_value = self.response(content=html)
        raw, records = fetch_fda_cyp_table(session)
        self.assertEqual(raw, html)
        self.assertEqual({row['role'] for row in records}, {'inhibitor', 'substrate'})
        self.assertEqual(records[0]['enzyme'], 'CYP3A4')

    def test_openfda_pagination_and_manual_review(self):
        label = {'set_id': 'set-1', 'effective_time': '20260101', 'id': 'spl-1',
                 'openfda': {'substance_name': ['Example A'], 'unii': ['U1']},
                 'drug_interactions': ['CYP3A4 inhibitor language']}
        session = Mock(); session.get.side_effect = [
            self.response(payload={'results': [label]}),
        ]
        raw, records = fetch_openfda_labels(effective_from='20260101', session=session)
        snapshot, _diff = store_snapshot(
            source='openfda', version='v1', url='https://api.fda.gov/drug/label.json', raw=raw, records=records,
        )
        queue_label_reviews(snapshot, records)
        review = MetabolicImportReview.objects.get()
        self.assertEqual(review.reason, 'label_text_requires_review')
        self.assertEqual(review.status, 'pending')
        self.assertIn('drug_interactions', review.raw_payload)

    def test_snapshot_is_idempotent_and_encrypted(self):
        raw = json.dumps([{'id': '1'}]).encode()
        first, _ = store_snapshot(source='fda', version='v1', url='https://example.test', raw=raw, records=[{'id': '1'}])
        second, diff = store_snapshot(source='fda', version='v1', url='https://example.test', raw=raw, records=[{'id': '1'}])
        self.assertEqual(first.id, second.id)
        self.assertIsNone(diff)
        self.assertNotIn(raw, bytes(first.encrypted_payload))
        self.assertEqual(MetabolicSourceSnapshot.objects.count(), 1)

    def test_snapshot_reports_changed_records(self):
        first, _ = store_snapshot(source='fda', version='v1', url='https://example.test',
                                  raw=b'first', records=[{'id': '1', 'strength': 'weak'}])
        _second, diff = store_snapshot(source='fda', version='v2', url='https://example.test',
                                       raw=b'second', records=[{'id': '1', 'strength': 'strong'}])
        self.assertEqual(diff.previous_snapshot, first)
        self.assertEqual(diff.changed, ['1'])
