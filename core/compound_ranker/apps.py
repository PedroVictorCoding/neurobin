from django.apps import AppConfig


class CompoundRankerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'compound_ranker'
    verbose_name = 'Compound Ranker'

    def ready(self):
        """Initialize the app when Django starts"""
        # Note: Database access is discouraged in ready() method
        # To initialize scoring categories, run: python manage.py init_categories
        pass
