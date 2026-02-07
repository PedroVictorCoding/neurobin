from django.core.management.base import BaseCommand
from django.db import models

from research.models import ResearchSnippet


class Command(BaseCommand):
    help = "Purge synthetic research snippets created by populate_all_data.py"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete matching snippets (default is dry-run).",
        )

    def handle(self, *args, **options):
        dummy_types = {"research_paper", "clinical_data", "mechanism_study"}
        example_prefix = "https://example.com/research/"

        qs = ResearchSnippet.objects.filter(
            models.Q(snippet_type__in=dummy_types)
            | models.Q(source_url__startswith=example_prefix)
        )

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No dummy research snippets found."))
            return

        if not options["apply"]:
            sample = list(qs.values_list("id", "title")[:10])
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run: {total} dummy research snippets would be deleted."
                )
            )
            if sample:
                self.stdout.write("Sample:")
                for snippet_id, title in sample:
                    self.stdout.write(f"- {snippet_id}: {title}")
            self.stdout.write("Run again with --apply to delete.")
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} dummy research snippets."))
