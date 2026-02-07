from django.core.management.base import BaseCommand
from django.utils import timezone

from research.importer import import_pubmed_for_compound
from research.models import ResearchImportJob


class Command(BaseCommand):
    help = "Process queued compound research import jobs (PubMed)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Max number of queued jobs to process.")
        parser.add_argument("--job", type=int, default=None, help="Process a single job id.")

    def handle(self, *args, **options):
        job_id = options.get("job")
        limit = options.get("limit")

        qs = ResearchImportJob.objects.filter(status="queued").order_by("created_at")
        if job_id:
            qs = ResearchImportJob.objects.filter(id=job_id)

        if limit:
            qs = qs[:limit]

        jobs = list(qs)
        if not jobs:
            self.stdout.write(self.style.WARNING("No queued research import jobs found."))
            return

        for job in jobs:
            job.status = "running"
            job.started_at = timezone.now()
            job.error_message = ""
            job.save(update_fields=["status", "started_at", "error_message"])

            try:
                imported, query = import_pubmed_for_compound(
                    job.compound,
                    requested_by=job.requested_by,
                    max_results=min(job.max_results, 10),
                    query=job.query or None,
                )
                job.imported_count = imported
                job.query = query
                job.status = "completed"
                job.finished_at = timezone.now()
                job.save(update_fields=["imported_count", "query", "status", "finished_at"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Completed job {job.id} for {job.compound.name}: {imported} snippets"
                    )
                )
            except Exception as exc:
                job.status = "failed"
                job.error_message = str(exc)
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "error_message", "finished_at"])
                self.stdout.write(self.style.ERROR(f"Job {job.id} failed: {exc}"))
