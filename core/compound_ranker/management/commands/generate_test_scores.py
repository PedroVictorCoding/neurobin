"""
Management command to generate sample scores for testing
"""
from django.core.management.base import BaseCommand
from django.db import transaction
import random

from compounds.models import Compound
from compound_ranker.models import ScoringCategory, CompoundScore


class Command(BaseCommand):
    help = 'Generate sample compound scores for testing (no ML required)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Limit number of compounds to score',
        )
        parser.add_argument(
            '--category',
            type=str,
            help='Specific category slug to score for',
        )

    def handle(self, *args, **options):
        limit = options.get('limit')
        category_slug = options.get('category')
        
        # Get compounds
        compounds = Compound.objects.all()[:limit]
        
        if not compounds.exists():
            self.stdout.write(
                self.style.WARNING('No compounds found in database')
            )
            return
        
        # Get categories
        if category_slug:
            try:
                categories = [ScoringCategory.objects.get(slug=category_slug, is_active=True)]
            except ScoringCategory.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Category "{category_slug}" not found')
                )
                return
        else:
            categories = ScoringCategory.objects.filter(is_active=True)
        
        if not categories:
            self.stdout.write(
                self.style.WARNING('No active categories found')
            )
            return
        
        self.stdout.write(f'Generating scores for {compounds.count()} compounds across {len(categories)} categories...')
        
        created_count = 0
        updated_count = 0
        
        with transaction.atomic():
            for compound in compounds:
                for category in categories:
                    # Simple scoring based on compound features
                    score = self.calculate_simple_score(compound, category)
                    confidence = random.uniform(0.6, 0.9)  # Random confidence
                    
                    score_obj, created = CompoundScore.objects.update_or_create(
                        compound=compound,
                        category=category,
                        defaults={
                            'score': score,
                            'confidence': confidence,
                            'model_version': 'test_v1.0',
                            'features_used': {
                                'method': 'simple_test',
                                'mechanisms_count': compound.mechanism_of_action.count(),
                                'has_chembl': bool(compound.chembl_id)
                            }
                        }
                    )
                    
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Generated scores: {created_count} created, {updated_count} updated'
            )
        )
        
        # Show some sample results
        self.stdout.write('\nSample Results:')
        for category in categories[:3]:  # Show first 3 categories
            top_scores = CompoundScore.objects.filter(
                category=category
            ).select_related('compound').order_by('-score')[:3]
            
            self.stdout.write(f'\nTop compounds in {category.name}:')
            for i, score in enumerate(top_scores, 1):
                self.stdout.write(
                    f'  {i}. {score.compound.name}: {score.score:.3f} '
                    f'(confidence: {score.confidence:.3f})'
                )

    def calculate_simple_score(self, compound, category):
        """Calculate a simple score based on compound features"""
        score = 0.3  # Base score
        
        # Mechanism matching (simplified)
        mechanisms = compound.mechanism_of_action.all()
        mechanism_keywords = self.get_category_keywords(category.slug)
        
        for mechanism in mechanisms:
            # Check target name and interaction type
            mechanism_text = ""
            if mechanism.target_name:
                mechanism_text += str(mechanism.target_name).lower()
            if mechanism.target_interaction:
                mechanism_text += " " + mechanism.target_interaction.lower()
            if mechanism.description:
                mechanism_text += " " + mechanism.description.lower()
            
            for keyword in mechanism_keywords:
                if keyword.lower() in mechanism_text:
                    score += 0.1
                    break
        
        # ChEMBL ID bonus
        if compound.chembl_id:
            score += 0.1
        
        # View count bonus (popularity)
        if compound.views > 0:
            score += min(0.1, compound.views * 0.001)
        
        # Random variation to make it interesting
        score += random.uniform(-0.05, 0.15)
        
        # Ensure score is in valid range
        return max(0.0, min(1.0, score))
    
    def get_category_keywords(self, category_slug):
        """Get relevant keywords for each category"""
        keywords_map = {
            'longevity': ['antioxidant', 'anti-aging', 'autophagy', 'sirtuins', 'telomerase'],
            'cognition': ['nootropic', 'neuroprotective', 'cholinesterase', 'nmda', 'cognitive'],
            'anabolic': ['anabolic', 'protein synthesis', 'mtor', 'growth', 'muscle'],
            'neuroprotective': ['neuroprotective', 'anti-inflammatory', 'antioxidant', 'brain'],
            'cardioprotective': ['cardioprotective', 'vasodilator', 'antihypertensive', 'heart'],
            'hepatoprotective': ['hepatoprotective', 'liver', 'detoxification', 'hepatic'],
            'mitochondrial': ['mitochondrial', 'energy', 'metabolism', 'oxidative', 'atp'],
            'antiinflammatory': ['anti-inflammatory', 'cox', 'nf-kb', 'cytokine', 'inflammation'],
            'metabolic': ['metabolic', 'insulin', 'glucose', 'diabetes', 'metabolism'],
            'immunomodulator': ['immunomodulator', 'immune', 'cytokine', 'th1', 'immunity'],
            'psychostimulant': ['stimulant', 'dopamine', 'norepinephrine', 'alertness', 'energy'],
            'mood_enhancer': ['antidepressant', 'serotonin', 'mood', 'anxiety', 'depression'],
            'stress_resilience': ['adaptogen', 'stress', 'cortisol', 'hpa', 'resilience'],
            'nootropic': ['nootropic', 'cognitive', 'memory', 'learning', 'focus']
        }
        
        return keywords_map.get(category_slug, ['general', 'health', 'beneficial'])
