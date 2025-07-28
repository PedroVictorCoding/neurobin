"""
Predictor for compound scoring using trained models
"""
import os
import pickle
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import numpy as np
import torch

from django.conf import settings
from django.db import transaction

from compounds.models import Compound
from compound_ranker.models import ScoringCategory, CompoundScore
from .trainer import CompoundTrainer
from .data_loader import CompoundFeatureExtractor

logger = logging.getLogger(__name__)


class CompoundPredictor:
    """Predictor for compound scores using trained models"""
    
    def __init__(self):
        self.model_dir = os.path.join(settings.BASE_DIR, 'ml_models', 'compound_ranker')
        self.loaded_models = {}  # Cache for loaded models
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    def get_latest_model_path(self, category_slug: str) -> Tuple[Optional[str], Optional[str]]:
        """Get paths to the latest model and feature extractor for a category"""
        if not os.path.exists(self.model_dir):
            return None, None
        
        # Find all model files for this category
        model_files = [
            f for f in os.listdir(self.model_dir)
            if f.startswith(f"{category_slug}_") and f.endswith('.pth')
        ]
        
        if not model_files:
            return None, None
        
        # Sort by modification time (latest first)
        model_files.sort(key=lambda f: os.path.getmtime(os.path.join(self.model_dir, f)), reverse=True)
        latest_model = model_files[0]
        
        # Get corresponding feature extractor
        extractor_file = latest_model.replace('.pth', '_extractor.pkl')
        
        model_path = os.path.join(self.model_dir, latest_model)
        extractor_path = os.path.join(self.model_dir, extractor_file)
        
        if not os.path.exists(extractor_path):
            return None, None
        
        return model_path, extractor_path
    
    def load_model(self, category_slug: str) -> Optional[CompoundTrainer]:
        """Load trained model for a category"""
        if category_slug in self.loaded_models:
            return self.loaded_models[category_slug]
        
        try:
            category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
            model_path, extractor_path = self.get_latest_model_path(category_slug)
            
            if not model_path or not extractor_path:
                logger.warning(f"No trained model found for category: {category_slug}")
                return None
            
            trainer = CompoundTrainer(category)
            trainer.load_model(model_path, extractor_path)
            
            self.loaded_models[category_slug] = trainer
            logger.info(f"Loaded model for category: {category_slug}")
            return trainer
            
        except ScoringCategory.DoesNotExist:
            logger.error(f"Category not found: {category_slug}")
            return None
        except Exception as e:
            logger.error(f"Failed to load model for {category_slug}: {str(e)}")
            return None
    
    def predict_compound_score(self, compound: Compound, category: ScoringCategory) -> Optional[CompoundScore]:
        """Predict score for a single compound in a category"""
        trainer = self.load_model(category.slug)
        if not trainer or not trainer.model or not trainer.feature_extractor:
            logger.warning(f"Model not available for category: {category.slug}")
            return None
        
        try:
            # Extract features for this compound
            X, compound_ids = trainer.feature_extractor.transform(
                Compound.objects.filter(id=compound.id)
            )
            
            if len(X) == 0:
                logger.warning(f"Could not extract features for compound: {compound.name}")
                return None
            
            # Make prediction
            trainer.model.eval()
            with torch.no_grad():
                X_tensor = torch.FloatTensor(X).to(trainer.device)
                outputs = trainer.model(X_tensor)
                
                score = float(outputs[0, 0].cpu().numpy())
                confidence = float(outputs[0, 1].cpu().numpy())
            
            # Ensure values are in valid range
            score = max(0.0, min(1.0, score))
            confidence = max(0.0, min(1.0, confidence))
            
            # Create or update CompoundScore
            compound_score, created = CompoundScore.objects.update_or_create(
                compound=compound,
                category=category,
                defaults={
                    'score': score,
                    'confidence': confidence,
                    'model_version': trainer.model_version,
                    'features_used': {
                        'feature_count': X.shape[1],
                        'prediction_timestamp': datetime.now().isoformat()
                    }
                }
            )
            
            if created:
                logger.info(f"Created new score for {compound.name} in {category.name}: {score:.3f}")
            else:
                logger.info(f"Updated score for {compound.name} in {category.name}: {score:.3f}")
            
            return compound_score
            
        except Exception as e:
            logger.error(f"Prediction failed for {compound.name} in {category.name}: {str(e)}")
            return None
    
    def predict_compound_all_categories(self, compound: Compound) -> List[CompoundScore]:
        """Predict scores for a compound across all active categories"""
        results = []
        categories = ScoringCategory.objects.filter(is_active=True)
        
        for category in categories:
            score_obj = self.predict_compound_score(compound, category)
            if score_obj:
                results.append(score_obj)
        
        return results
    
    def batch_predict(self, compounds: List[Compound], category: ScoringCategory) -> List[CompoundScore]:
        """Predict scores for multiple compounds in a category"""
        trainer = self.load_model(category.slug)
        if not trainer or not trainer.model or not trainer.feature_extractor:
            logger.warning(f"Model not available for category: {category.slug}")
            return []
        
        try:
            # Extract features for all compounds
            compound_queryset = Compound.objects.filter(id__in=[c.id for c in compounds])
            X, compound_ids = trainer.feature_extractor.transform(compound_queryset)
            
            if len(X) == 0:
                logger.warning("Could not extract features for any compounds")
                return []
            
            # Make predictions
            trainer.model.eval()
            results = []
            
            with torch.no_grad():
                X_tensor = torch.FloatTensor(X).to(trainer.device)
                outputs = trainer.model(X_tensor)
                
                scores = outputs[:, 0].cpu().numpy()
                confidences = outputs[:, 1].cpu().numpy()
            
            # Create CompoundScore objects
            with transaction.atomic():
                for i, compound_id in enumerate(compound_ids):
                    try:
                        compound = Compound.objects.get(id=compound_id)
                        score = max(0.0, min(1.0, float(scores[i])))
                        confidence = max(0.0, min(1.0, float(confidences[i])))
                        
                        compound_score, created = CompoundScore.objects.update_or_create(
                            compound=compound,
                            category=category,
                            defaults={
                                'score': score,
                                'confidence': confidence,
                                'model_version': trainer.model_version,
                                'features_used': {
                                    'feature_count': X.shape[1],
                                    'batch_prediction': True,
                                    'prediction_timestamp': datetime.now().isoformat()
                                }
                            }
                        )
                        results.append(compound_score)
                        
                    except Compound.DoesNotExist:
                        continue
            
            logger.info(f"Batch predicted {len(results)} scores for {category.name}")
            return results
            
        except Exception as e:
            logger.error(f"Batch prediction failed for {category.name}: {str(e)}")
            return []
    
    def update_all_scores(self, force_update: bool = False) -> Dict[str, int]:
        """Update scores for all compounds across all categories"""
        results = {}
        categories = ScoringCategory.objects.filter(is_active=True)
        compounds = list(Compound.objects.all())
        
        for category in categories:
            try:
                if not force_update:
                    # Only update compounds without scores
                    existing_compound_ids = set(
                        CompoundScore.objects.filter(category=category)
                        .values_list('compound_id', flat=True)
                    )
                    compounds_to_update = [
                        c for c in compounds if c.id not in existing_compound_ids
                    ]
                else:
                    compounds_to_update = compounds
                
                if compounds_to_update:
                    scores = self.batch_predict(compounds_to_update, category)
                    results[category.slug] = len(scores)
                else:
                    results[category.slug] = 0
                    
            except Exception as e:
                logger.error(f"Failed to update scores for {category.name}: {str(e)}")
                results[category.slug] = 0
        
        return results


# Global predictor instance
_global_predictor = None


def get_predictor() -> CompoundPredictor:
    """Get global predictor instance"""
    global _global_predictor
    if _global_predictor is None:
        _global_predictor = CompoundPredictor()
    return _global_predictor


def predict_compound_scores(compound: Compound, category: ScoringCategory = None) -> List[CompoundScore]:
    """Convenience function to predict compound scores"""
    predictor = get_predictor()
    
    if category:
        result = predictor.predict_compound_score(compound, category)
        return [result] if result else []
    else:
        return predictor.predict_compound_all_categories(compound)


def initialize_categories():
    """Initialize default scoring categories"""
    default_categories = [
        {
            'name': 'Longevity-enhancing',
            'slug': 'longevity',
            'description': 'Improves lifespan markers and healthspan indicators',
            'icon': '⏳'
        },
        {
            'name': 'Cognitive enhancer',
            'slug': 'cognition',
            'description': 'Improves memory, attention, and cognitive performance',
            'icon': '🧠'
        },
        {
            'name': 'Anabolic',
            'slug': 'anabolic',
            'description': 'Increases lean mass or muscle protein synthesis',
            'icon': '💪'
        },
        {
            'name': 'Neuroprotective',
            'slug': 'neuroprotective',
            'description': 'Prevents neurodegeneration and protects neural function',
            'icon': '🛡️'
        },
        {
            'name': 'Cardioprotective',
            'slug': 'cardioprotective',
            'description': 'Supports cardiovascular health and heart function',
            'icon': '❤️'
        },
        {
            'name': 'Liver-protective',
            'slug': 'hepatoprotective',
            'description': 'Reduces liver toxicity or damage',
            'icon': '🫀'
        },
        {
            'name': 'Mitochondrial enhancer',
            'slug': 'mitochondrial',
            'description': 'Boosts energy metabolism and mitochondrial function',
            'icon': '⚡'
        },
        {
            'name': 'Anti-inflammatory',
            'slug': 'antiinflammatory',
            'description': 'Reduces inflammatory markers and responses',
            'icon': '🔥'
        },
        {
            'name': 'Metabolic stabilizer',
            'slug': 'metabolic',
            'description': 'Improves insulin sensitivity and metabolic health',
            'icon': '⚖️'
        },
        {
            'name': 'Immunomodulator',
            'slug': 'immunomodulator',
            'description': 'Supports immune balance and function',
            'icon': '🦠'
        },
        {
            'name': 'Psychostimulant',
            'slug': 'psychostimulant',
            'description': 'Increases alertness, focus, and mental energy',
            'icon': '⚡'
        },
        {
            'name': 'Mood enhancer',
            'slug': 'mood_enhancer',
            'description': 'Positively affects mood and emotional well-being',
            'icon': '😊'
        },
        {
            'name': 'Stress resilience',
            'slug': 'stress_resilience',
            'description': 'Adaptogenic effects and stress resistance',
            'icon': '🧘'
        },
        {
            'name': 'Nootropic',
            'slug': 'nootropic',
            'description': 'Broad cognitive support and mental enhancement',
            'icon': '🎯'
        }
    ]
    
    for category_data in default_categories:
        ScoringCategory.objects.get_or_create(
            slug=category_data['slug'],
            defaults=category_data
        )
