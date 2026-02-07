from celery import shared_task

from .importer import process_import_job


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def run_import_job(self, job_id: int):
    process_import_job(job_id)
