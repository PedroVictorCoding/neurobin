from django.apps import AppConfig


class CompoundRankerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'compound_ranker'
    verbose_name = 'Compound Ranker'

    def ready(self):
        """Initialize the app when Django starts"""
        try:
            from .ml.predictor import initialize_categories
            initialize_categories()
        except ImportError:
            # ML dependencies not installed, skip initialization
            import logging
            logger = logging.getLogger(__name__)
            logger.info("ML dependencies not available, skipping category initialization")
        except Exception:
            # Don't fail during migrations or initial setup
            pass
