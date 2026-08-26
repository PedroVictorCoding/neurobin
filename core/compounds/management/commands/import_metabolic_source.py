import json

from django.core.management.base import BaseCommand, CommandError

from compounds.metabolic_import import import_metabolic_source


class Command(BaseCommand):
    help = 'Import versioned FDA, DailyMed/openFDA, or optional ClinPGx metabolic-role records.'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, choices=['fda', 'dailymed', 'openfda', 'clinpgx'])
        parser.add_argument('--source-version', required=True)
        parser.add_argument('--input', required=True, help='JSON/CSV path or HTTPS URL')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--enable-clinpgx', action='store_true')

    def handle(self, *args, **options):
        if options['source'] == 'clinpgx' and not options['enable_clinpgx']:
            raise CommandError('ClinPGx import is disabled; pass --enable-clinpgx after reviewing its data terms.')
        tier = 'label_clinical' if options['source'] in {'fda', 'dailymed', 'openfda'} else 'curated_human'
        result = import_metabolic_source(
            source=options['source'], source_version=options['source_version'],
            location=options['input'], evidence_tier=tier, dry_run=options['dry_run'],
        )
        self.stdout.write(json.dumps(result, sort_keys=True))
