"""
Advanced model training command with enhanced features
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from compound_ranker.models import ScoringCategory
from compound_ranker.ml.trainer import CompoundTrainer, train_all_models
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Train advanced neural network models for compound scoring'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            type=str,
            help='Specific category slug to train for',
        )
        parser.add_argument(
            '--all-categories',
            action='store_true',
            help='Train models for all active categories',
        )
        parser.add_argument(
            '--epochs',
            type=int,
            default=150,
            help='Number of training epochs (default: 150)',
        )
        parser.add_argument(
            '--advanced',
            action='store_true',
            default=True,
            help='Use advanced model architecture (default: True)',
        )
        parser.add_argument(
            '--standard',
            action='store_true',
            help='Use standard model architecture instead of advanced',
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Username of user initiating training',
        )

    def handle(self, *args, **options):
        epochs = options.get('epochs')
        category_slug = options.get('category')
        all_categories = options.get('all_categories')
        use_advanced = not options.get('standard', False)  # Default to advanced unless --standard
        username = options.get('user')
        
        # Get user if specified
        user = None
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'User "{username}" not found, proceeding without user')
                )
        
        model_type = "Advanced" if use_advanced else "Standard"
        self.stdout.write(f'Starting {model_type} model training...')
        
        if all_categories:
            self.stdout.write(f'Training {model_type.lower()} models for all active categories...')
            results = train_all_models(epochs=epochs, user=user, use_advanced=use_advanced)
            
            # Report results
            successful = sum(1 for r in results.values() if r.get('success', False))
            total = len(results)
            
            self.stdout.write(f'\n=== TRAINING RESULTS ===')
            self.stdout.write(f'Successful: {successful}/{total}')
            
            for category_slug, result in results.items():
                if result.get('success', False):
                    metrics = result.get('test_metrics', {})
                    score_r2 = metrics.get('score_r2', 0)
                    score_mse = metrics.get('score_mse', 0)
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ {category_slug}: R² = {score_r2:.3f}, MSE = {score_mse:.4f}'
                        )
                    )
                else:
                    error = result.get('error', 'Unknown error')
                    self.stdout.write(
                        self.style.ERROR(f'✗ {category_slug}: {error}')
                    )
        
        elif category_slug:
            try:
                category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
                self.stdout.write(f'Training {model_type.lower()} model for "{category.name}"...')
                
                trainer = CompoundTrainer(category, use_advanced_model=use_advanced)
                result = trainer.train_model(epochs=epochs, user=user)
                
                if result.get('success', False):
                    metrics = result.get('test_metrics', {})
                    history = result.get('training_history', {})
                    
                    self.stdout.write(
                        self.style.SUCCESS(f'Training completed successfully!')
                    )
                    
                    # Display key metrics
                    self.stdout.write('\n=== FINAL METRICS ===')
                    for metric_name, value in metrics.items():
                        self.stdout.write(f'{metric_name}: {value:.4f}')
                    
                    # Display training summary
                    if history:
                        final_train_loss = history['train_losses'][-1] if history.get('train_losses') else 'N/A'
                        final_val_loss = history['val_losses'][-1] if history.get('val_losses') else 'N/A'
                        self.stdout.write(f'\nFinal train loss: {final_train_loss}')
                        self.stdout.write(f'Final validation loss: {final_val_loss}')
                        self.stdout.write(f'Total epochs: {len(history.get("train_losses", []))}')
                    
                    model_path = result.get('model_path', 'Unknown')
                    self.stdout.write(f'Model saved to: {model_path}')
                
                else:
                    error = result.get('error', 'Unknown error')
                    self.stdout.write(
                        self.style.ERROR(f'Training failed: {error}')
                    )
            
            except ScoringCategory.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Category "{category_slug}" not found or inactive')
                )
        
        else:
            self.stdout.write(
                self.style.ERROR('Please specify either --category <slug> or --all-categories')
            )
            return
        
        self.stdout.write('\n=== TRAINING COMPLETE ===')
        
        # Show available models
        self.stdout.write('\nAvailable categories for training:')
        for category in ScoringCategory.objects.filter(is_active=True):
            self.stdout.write(f'  - {category.slug}: {category.name}')
