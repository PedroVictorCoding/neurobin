"""
Management command to train compound scoring models
"""
import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from compound_ranker.models import ScoringCategory
from compound_ranker.ml.trainer import train_category_model, train_all_models


class Command(BaseCommand):
    help = 'Train compound scoring models'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            type=str,
            help='Category slug to train (if not specified, trains all categories)',
        )
        parser.add_argument(
            '--epochs',
            type=int,
            default=100,
            help='Number of training epochs (default: 100)',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite existing model',
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Username of the user initiating training',
        )

    def handle(self, *args, **options):
        category = options.get('category')
        epochs = options.get('epochs')
        overwrite = options.get('overwrite')
        username = options.get('user')
        
        # Get user if specified
        user = None
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'User "{username}" not found, proceeding without user attribution')
                )

        try:
            if category:
                # Train specific category
                try:
                    cat_obj = ScoringCategory.objects.get(slug=category, is_active=True)
                except ScoringCategory.DoesNotExist:
                    raise CommandError(f'Category "{category}" not found or inactive')

                self.stdout.write(f'Training model for category: {cat_obj.name}')
                
                if not overwrite:
                    # Check if model already exists
                    from compound_ranker.ml.trainer import CompoundTrainer
                    trainer = CompoundTrainer(cat_obj)
                    if os.path.exists(trainer.get_model_path()):
                        raise CommandError(
                            f'Model for category "{category}" already exists. Use --overwrite to replace it.'
                        )

                result = train_category_model(category, epochs=epochs, user=user)
                
                if 'error' in result:
                    raise CommandError(f'Training failed: {result["error"]}')
                
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully trained model for {cat_obj.name}')
                )
                self.stdout.write(f'Model saved to: {result["model_path"]}')
                
                # Display training metrics
                if 'test_metrics' in result:
                    metrics = result['test_metrics']
                    self.stdout.write('\nTraining Results:')
                    self.stdout.write(f'  R² Score: {metrics.get("r2_score", "N/A"):.4f}')
                    self.stdout.write(f'  RMSE: {metrics.get("rmse", "N/A"):.4f}')
                    self.stdout.write(f'  MAE: {metrics.get("mae", "N/A"):.4f}')

            else:
                # Train all categories
                self.stdout.write('Training models for all active categories...')
                
                results = train_all_models(epochs=epochs, user=user)
                
                success_count = 0
                failed_count = 0
                
                for cat_slug, result in results.items():
                    if 'error' in result:
                        self.stdout.write(
                            self.style.ERROR(f'Failed to train {cat_slug}: {result["error"]}')
                        )
                        failed_count += 1
                    else:
                        self.stdout.write(
                            self.style.SUCCESS(f'Successfully trained {cat_slug}')
                        )
                        success_count += 1

                self.stdout.write(f'\nTraining Summary:')
                self.stdout.write(f'  Successful: {success_count}')
                self.stdout.write(f'  Failed: {failed_count}')
                
                if failed_count > 0:
                    self.stdout.write(
                        self.style.WARNING('Some models failed to train. Check logs for details.')
                    )

        except ImportError as e:
            raise CommandError(
                f'Required ML libraries not installed: {str(e)}\n'
                'Install with: pip install torch scikit-learn numpy pandas'
            )
        except Exception as e:
            raise CommandError(f'Training failed: {str(e)}')
