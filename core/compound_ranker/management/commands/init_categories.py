"""
Management command to initialize compound ranking categories
"""
from django.core.management.base import BaseCommand

from compound_ranker.models import ScoringCategory


class Command(BaseCommand):
    help = 'Initialize default compound scoring categories'

    def handle(self, *args, **options):
        default_categories = [
            {
                'name': 'Longevity-enhancing',
                'slug': 'longevity',
                'description': 'Compounds that may improve lifespan markers and anti-aging processes',
                'icon': '⏳'
            },
            {
                'name': 'Cognitive enhancer',
                'slug': 'cognition',
                'description': 'Compounds that may improve memory, attention, and cognitive function',
                'icon': '🧠'
            },
            {
                'name': 'Anabolic',
                'slug': 'anabolic',
                'description': 'Compounds that may increase lean mass or muscle protein synthesis',
                'icon': '💪'
            },
            {
                'name': 'Neuroprotective',
                'slug': 'neuroprotective',
                'description': 'Compounds that may prevent neurodegeneration and protect brain health',
                'icon': '🛡️'
            },
            {
                'name': 'Cardioprotective',
                'slug': 'cardioprotective',
                'description': 'Compounds that may support cardiovascular health',
                'icon': '❤️'
            },
            {
                'name': 'Liver-protective',
                'slug': 'hepatoprotective',
                'description': 'Compounds that may reduce liver toxicity or damage',
                'icon': '🫀'
            },
            {
                'name': 'Mitochondrial enhancer',
                'slug': 'mitochondrial',
                'description': 'Compounds that may boost energy metabolism and mitochondrial function',
                'icon': '⚡'
            },
            {
                'name': 'Anti-inflammatory',
                'slug': 'antiinflammatory',
                'description': 'Compounds that may reduce inflammatory markers',
                'icon': '🔥'
            },
            {
                'name': 'Metabolic stabilizer',
                'slug': 'metabolic',
                'description': 'Compounds that may improve insulin sensitivity and metabolic health',
                'icon': '⚖️'
            },
            {
                'name': 'Immunomodulator',
                'slug': 'immunomodulator',
                'description': 'Compounds that may support immune system balance',
                'icon': '🛡️'
            },
            {
                'name': 'Psychostimulant',
                'slug': 'psychostimulant',
                'description': 'Compounds that may increase alertness and focus',
                'icon': '⚡'
            },
            {
                'name': 'Mood enhancer',
                'slug': 'mood_enhancer',
                'description': 'Compounds that may positively affect mood and well-being',
                'icon': '😊'
            },
            {
                'name': 'Stress resilience',
                'slug': 'stress_resilience',
                'description': 'Compounds with adaptogenic effects that may help manage stress',
                'icon': '🧘'
            },
            {
                'name': 'Nootropic',
                'slug': 'nootropic',
                'description': 'Compounds that may provide broad cognitive support',
                'icon': '🎯'
            }
        ]
        
        created_count = 0
        for cat_data in default_categories:
            category, created = ScoringCategory.objects.get_or_create(
                slug=cat_data['slug'],
                defaults=cat_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created category: {category.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Category already exists: {category.name}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'\nInitialized {created_count} new categories out of {len(default_categories)} total')
        )
