import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .tasks import run_import_job
from .models import ResearchImportJob

logger = logging.getLogger(__name__)


def _enqueue_research_import_job(job_id: int) -> None:
    """
    Best-effort async dispatch.
    Keep the DB job queued if broker/backends are unavailable.
    """
    try:
        # Avoid result-backend dependency for fire-and-forget queueing.
        run_import_job.apply_async(args=[job_id], ignore_result=True)
    except Exception:
        logger.exception("Failed to enqueue ResearchImportJob id=%s; job remains queued.", job_id)


@receiver(post_save, sender=ResearchImportJob)
def auto_process_research_import(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.status != "queued":
        return

    transaction.on_commit(
        lambda: _enqueue_research_import_job(instance.id),
        robust=True,
    )
