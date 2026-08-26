import json
import os
import tempfile

from django.core.management.base import BaseCommand
from django.utils import timezone

from compounds.metabolic_import import import_metabolic_source
from compounds.source_adapters import (
    FDA_CYP_URL, OPENFDA_LABEL_URL, fetch_fda_cyp_table, fetch_openfda_labels,
    queue_label_reviews, store_snapshot,
)


class Command(BaseCommand):
    help = 'Fetch versioned FDA CYP classifications and openFDA label review candidates.'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['fda', 'openfda', 'all'], default='all')
        parser.add_argument('--effective-from', default=timezone.now().strftime('%Y0101'))
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        version = timezone.now().strftime('%Y-%m-%d')
        output = {}
        if options['source'] in {'fda', 'all'}:
            raw, records = fetch_fda_cyp_table()
            if not options['dry_run']:
                snapshot, diff = store_snapshot(source='fda', version=version, url=FDA_CYP_URL, raw=raw, records=records)
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as handle:
                    json.dump(records, handle); handle.flush()
                    output['fda_import'] = import_metabolic_source(
                        source='fda', source_version=version, location=handle.name,
                        evidence_tier='label_clinical', dry_run=False,
                    )
                output['fda_snapshot'] = snapshot.id
                output['fda_diff'] = diff.id if diff else None
            else:
                output['fda_records'] = len(records)
        if options['source'] in {'openfda', 'all'}:
            raw, records = fetch_openfda_labels(
                effective_from=options['effective_from'], api_key=os.getenv('OPENFDA_API_KEY', ''),
            )
            if not options['dry_run']:
                snapshot, diff = store_snapshot(source='openfda', version=version, url=OPENFDA_LABEL_URL, raw=raw, records=records)
                queue_label_reviews(snapshot, records)
                output['openfda_snapshot'] = snapshot.id
                output['openfda_review_records'] = len(records)
                output['openfda_diff'] = diff.id if diff else None
            else:
                output['openfda_records'] = len(records)
        self.stdout.write(json.dumps(output, sort_keys=True))
