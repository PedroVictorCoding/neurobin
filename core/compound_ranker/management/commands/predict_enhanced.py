"""
Enhanced prediction command using ensemble methods and uncertainty quantification
"""
from django.core.management.base import BaseCommand
from compound_ranker.models import ScoringCategory, CompoundScore
from compound_ranker.ml.predictor import EnhancedCompoundPredictor
from compounds.models import Compound
import time


class Command(BaseCommand):
    help = 'Generate predictions using enhanced ensemble models'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            type=str,
            help='Specific category slug to predict for',
        )
        parser.add_argument(
            '--all-categories',
            action='store_true',
            help='Predict for all active categories',
        )
        parser.add_argument(
            '--top-only',
            type=int,
            default=0,
            help='Only predict for top N compounds (0 = all compounds)',
        )
        parser.add_argument(
            '--ensemble',
            action='store_true',
            default=True,
            help='Use ensemble prediction (default: True)',
        )
        parser.add_argument(
            '--show-uncertainty',
            action='store_true',
            help='Display uncertainty metrics',
        )

    def handle(self, *args, **options):
        category_slug = options.get('category')
        all_categories = options.get('all_categories')
        top_only = options.get('top_only')
        use_ensemble = options.get('ensemble')
        show_uncertainty = options.get('show_uncertainty')
        
        predictor = EnhancedCompoundPredictor()
        
        # Determine categories to process
        if all_categories:
            categories = ScoringCategory.objects.filter(is_active=True)
        elif category_slug:
            try:
                categories = [ScoringCategory.objects.get(slug=category_slug, is_active=True)]
            except ScoringCategory.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Category "{category_slug}" not found or inactive')
                )
                return
        else:
            self.stdout.write(
                self.style.ERROR('Please specify either --category <slug> or --all-categories')
            )
            return
        
        # Get compounds to process
        compounds = list(Compound.objects.all())
        if top_only > 0:
            compounds = compounds[:top_only]
        
        self.stdout.write(f'Processing {len(compounds)} compounds across {len(categories)} categories...')
        
        total_predictions = 0
        total_time = 0
        
        for category in categories:
            self.stdout.write(f'\n=== {category.name} ===')
            
            start_time = time.time()
            
            if use_ensemble:
                # Enhanced ensemble prediction
                scores = predictor.batch_predict_enhanced(compounds, category)
            else:
                # Standard prediction
                standard_predictor = CompoundPredictor()
                scores = []
                for compound in compounds:
                    score = standard_predictor.predict_compound_score(compound, category)
                    if score:
                        scores.append(score)
            
            category_time = time.time() - start_time
            total_time += category_time
            total_predictions += len(scores)
            
            self.stdout.write(f'Generated {len(scores)} predictions in {category_time:.2f}s')
            
            if scores:
                # Sort by weighted score (score * confidence)
                scores.sort(key=lambda x: x.score * x.confidence, reverse=True)
                
                # Display top 5 results
                self.stdout.write('Top 5 compounds:')
                for i, score in enumerate(scores[:5], 1):
                    weighted_score = score.score * score.confidence
                    
                    uncertainty_info = ""
                    if show_uncertainty and 'total_uncertainty' in score.features_used:
                        uncertainty = score.features_used['total_uncertainty']
                        uncertainty_info = f" (uncertainty: {uncertainty:.3f})"
                    
                    self.stdout.write(
                        f'  {i}. {score.compound.name}: {score.score:.3f} '
                        f'(confidence: {score.confidence:.3f}, '
                        f'weighted: {weighted_score:.3f}){uncertainty_info}'
                    )
                
                # Display uncertainty statistics if requested
                if show_uncertainty:
                    ensemble_scores = [s for s in scores if 'ensemble_size' in s.features_used]
                    if ensemble_scores:
                        avg_uncertainty = sum(
                            s.features_used.get('total_uncertainty', 0) for s in ensemble_scores
                        ) / len(ensemble_scores)
                        
                        avg_variance = sum(
                            s.features_used.get('prediction_variance', 0) for s in ensemble_scores
                        ) / len(ensemble_scores)
                        
                        self.stdout.write(f'Average uncertainty: {avg_uncertainty:.4f}')
                        self.stdout.write(f'Average prediction variance: {avg_variance:.4f}')
            
            else:
                self.stdout.write(self.style.WARNING('No predictions generated'))
        
        # Final summary
        self.stdout.write(f'\n=== SUMMARY ===')
        self.stdout.write(f'Total predictions: {total_predictions}')
        self.stdout.write(f'Total time: {total_time:.2f}s')
        self.stdout.write(f'Average time per prediction: {total_time/max(total_predictions, 1):.3f}s')
        
        # Show model availability
        self.stdout.write('\n=== MODEL AVAILABILITY ===')
        for category in categories:
            ensemble_models = predictor.load_ensemble_models(category.slug)
            if ensemble_models:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ {category.slug}: {len(ensemble_models)} ensemble models available'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠ {category.slug}: No models available')
                )
