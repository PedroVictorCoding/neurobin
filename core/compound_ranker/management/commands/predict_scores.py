"""
Management command to predict compound scores
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from compounds.models import Compound
from compound_ranker.models import ScoringCategory
from compound_ranker.ml.predictor import predict_all_compounds, predict_compound_scores


class Command(BaseCommand):
    help = 'Predict compound scores using trained models'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            type=str,
            help='Category slug to predict for (if not specified, predicts for all categories)',
        )
        parser.add_argument(
            '--compound',
            type=str,
            help='Specific compound name or ChEMBL ID to predict for',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of compounds to process',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force prediction even if scores already exist',
        )

    def handle(self, *args, **options):
        category_slug = options.get('category')
        compound_name = options.get('compound')
        limit = options.get('limit')
        force = options.get('force')

        try:
            if compound_name:
                # Predict for specific compound
                try:
                    # Try to find by name first, then by ChEMBL ID
                    try:
                        compound = Compound.objects.get(name__iexact=compound_name)
                    except Compound.DoesNotExist:
                        compound = Compound.objects.get(chembl_id__iexact=compound_name)
                except Compound.DoesNotExist:
                    raise CommandError(f'Compound "{compound_name}" not found')

                self.stdout.write(f'Predicting scores for: {compound.name}')
                
                if category_slug:
                    try:
                        category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
                        score_obj = predict_compound_scores(compound, category)
                        if score_obj:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'Predicted score for {compound.name} in {category.name}: '
                                    f'{score_obj.score:.3f} (confidence: {score_obj.confidence:.3f})'
                                )
                            )
                        else:
                            self.stdout.write(
                                self.style.WARNING(f'Failed to predict score for {compound.name}')
                            )
                    except ScoringCategory.DoesNotExist:
                        raise CommandError(f'Category "{category_slug}" not found or inactive')
                else:
                    # Predict for all categories
                    scores = predict_compound_scores(compound)
                    if scores:
                        self.stdout.write(
                            self.style.SUCCESS(f'Predicted scores for {compound.name} across all categories')
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'Failed to predict scores for {compound.name}')
                        )

            else:
                # Predict for all compounds (or subset)
                self.stdout.write('Starting bulk prediction...')
                
                if category_slug:
                    try:
                        category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
                        self.stdout.write(f'Predicting for category: {category.name}')
                    except ScoringCategory.DoesNotExist:
                        raise CommandError(f'Category "{category_slug}" not found or inactive')
                else:
                    categories = ScoringCategory.objects.filter(is_active=True)
                    self.stdout.write(f'Predicting for {categories.count()} categories')

                # Show current status
                total_compounds = Compound.objects.count()
                if limit:
                    self.stdout.write(f'Processing {limit} of {total_compounds} compounds')
                else:
                    self.stdout.write(f'Processing all {total_compounds} compounds')

                # Run prediction
                results = predict_all_compounds(category_slug, limit)
                
                self.stdout.write('\nPrediction Results:')
                self.stdout.write(f'  Updated scores: {results["updated"]}')
                self.stdout.write(f'  Errors: {results["errors"]}')
                
                if results['errors'] > 0:
                    self.stdout.write(
                        self.style.WARNING('Some predictions failed. Check logs for details.')
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS('All predictions completed successfully!')
                    )

        except Exception as e:
            raise CommandError(f'Prediction failed: {str(e)}')
