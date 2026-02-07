from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .tasks import run_import_job
from .models import ResearchImportJob


@receiver(post_save, sender=ResearchImportJob)
def auto_process_research_import(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.status != "queued":
        return

    transaction.on_commit(lambda: run_import_job.delay(instance.id))
