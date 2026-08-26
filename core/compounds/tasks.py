from celery import shared_task
from django.core.management import call_command


@shared_task
def sync_official_metabolic_sources_task():
    call_command('sync_official_metabolic_sources', source='all')
