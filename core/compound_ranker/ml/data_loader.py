"""
Data loader for extracting features from compounds for ML training
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from django.db.models import QuerySet, Max, Min, Avg, Count
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer

from compounds.models import (
    Compound, CompoundTargetInteraction, Target, 
    CompoundMechanismOfAction, ActionType, TargetType
)
from compound_ranker.models import ScoringCategory, CompoundScore, UserCompoundAnnotation


class CompoundFeatureExtractor:
    """Extract features from compounds for ML training"""
    
    def __init__(self):
        self.mechanism_encoder = None
        self.target_encoder = None
        self.action_encoder = None
        self.scaler = StandardScaler()
        self.tfidf_vectorizer = TfidfVectorizer(max_features=100, stop_words='english')
        self.feature_names = []
        self.is_fitted = False
    
    def extract_basic_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract basic compound features"""
        features = []
        
        for compound in compounds:
            feature_dict = {
                'compound_id': compound.id,
                'has_chembl_id': bool(compound.chembl_id),
                'has_smiles': bool(compound.smiles),
                'name_length': len(compound.name),
                'description_length': len(compound.description) if compound.description else 0,
                'alias_count': len(compound.aliases.split(',')) if compound.aliases else 0,
                'category_count': compound.categories.count(),
                'mechanism_count': compound.mechanism_of_action.count(),
                'view_count': compound.views,
            }
            features.append(feature_dict)
        
        return pd.DataFrame(features)
    
    def extract_interaction_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract target interaction features"""
        from django.db.models import Count, Avg
        
        features = []
        
        for compound in compounds:
            # Get interactions for this compound
            interactions = CompoundTargetInteraction.objects.filter(
                compoundtocompoundtargetinteraction__compound_a=compound
            ) | CompoundTargetInteraction.objects.filter(
                compoundtocompoundtargetinteraction__compound_b=compound
            )
            
            # Aggregate interaction features
            feature_dict = {
                'compound_id': compound.id,
                'total_interactions': interactions.count(),
                'unique_targets': interactions.values('target').distinct().count(),
                'avg_affinity': interactions.aggregate(Avg('affinity'))['affinity__avg'] or 0,
                'max_affinity': interactions.aggregate(max_aff=Max('affinity'))['max_aff'] or 0,
            }
            
            # Target type distribution
            target_types = interactions.values_list('target__type__name', flat=True)
            for target_type in TargetType.objects.all():
                feature_dict[f'target_type_{target_type.name}'] = list(target_types).count(target_type.name)
            
            # Action type distribution
            action_types = interactions.values_list('action_type__name', flat=True)
            for action_type in ActionType.objects.all():
                feature_dict[f'action_type_{action_type.name}'] = list(action_types).count(action_type.name)
            
            features.append(feature_dict)
        
        return pd.DataFrame(features).fillna(0)
    
    def extract_mechanism_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract mechanism of action features as multi-hot encoding"""
        features = []
        all_mechanisms = CompoundMechanismOfAction.objects.all()
        
        for compound in compounds:
            compound_mechanisms = set(compound.mechanism_of_action.values_list('id', flat=True))
            
            feature_dict = {'compound_id': compound.id}
            
            # Multi-hot encoding for mechanisms
            for mechanism in all_mechanisms:
                feature_dict[f'mechanism_{mechanism.id}'] = int(mechanism.id in compound_mechanisms)
            
            features.append(feature_dict)
        
        return pd.DataFrame(features).fillna(0)
    
    def extract_text_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract TF-IDF features from compound descriptions"""
        texts = []
        compound_ids = []
        
        for compound in compounds:
            # Combine available text fields
            text_parts = [compound.name]
            if compound.description:
                text_parts.append(compound.description)
            if compound.aliases:
                text_parts.append(compound.aliases)
            
            # Add mechanism names
            mechanism_names = compound.mechanism_of_action.values_list('name', flat=True)
            text_parts.extend(mechanism_names)
            
            texts.append(' '.join(text_parts))
            compound_ids.append(compound.id)
        
        if not self.is_fitted:
            tfidf_matrix = self.tfidf_vectorizer.fit_transform(texts)
        else:
            tfidf_matrix = self.tfidf_vectorizer.transform(texts)
        
        # Convert to DataFrame
        feature_names = [f'tfidf_{i}' for i in range(tfidf_matrix.shape[1])]
        tfidf_df = pd.DataFrame(
            tfidf_matrix.toarray(),
            columns=feature_names
        )
        tfidf_df['compound_id'] = compound_ids
        
        return tfidf_df
    
    def extract_all_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract all features and combine into single DataFrame"""
        # Extract different feature types
        basic_df = self.extract_basic_features(compounds)
        interaction_df = self.extract_interaction_features(compounds)
        mechanism_df = self.extract_mechanism_features(compounds)
        text_df = self.extract_text_features(compounds)
        
        # Merge all features
        features_df = basic_df
        for df in [interaction_df, mechanism_df, text_df]:
            features_df = features_df.merge(df, on='compound_id', how='left')
        
        # Fill NaN values
        features_df = features_df.fillna(0)
        
        # Store feature names
        self.feature_names = [col for col in features_df.columns if col != 'compound_id']
        
        return features_df
    
    def fit_transform(self, compounds: QuerySet) -> Tuple[np.ndarray, List[int]]:
        """Fit scalers and transform compounds to feature matrix"""
        features_df = self.extract_all_features(compounds)
        
        compound_ids = features_df['compound_id'].values
        feature_matrix = features_df.drop('compound_id', axis=1).values
        
        # Fit and transform features
        feature_matrix = self.scaler.fit_transform(feature_matrix)
        self.is_fitted = True
        
        return feature_matrix, compound_ids
    
    def transform(self, compounds: QuerySet) -> Tuple[np.ndarray, List[int]]:
        """Transform compounds to feature matrix using fitted scalers"""
        if not self.is_fitted:
            raise ValueError("FeatureExtractor must be fitted before transform")
        
        features_df = self.extract_all_features(compounds)
        
        compound_ids = features_df['compound_id'].values
        feature_matrix = features_df.drop('compound_id', axis=1).values
        
        # Transform features
        feature_matrix = self.scaler.transform(feature_matrix)
        
        return feature_matrix, compound_ids


class TrainingDataLoader:
    """Load training data for compound scoring models"""
    
    def __init__(self, category: ScoringCategory):
        self.category = category
        self.feature_extractor = CompoundFeatureExtractor()
    
    def get_labeled_compounds(self) -> QuerySet:
        """Get compounds with known scores/annotations for this category"""
        # Get compounds with ML scores
        ml_scored_compounds = Compound.objects.filter(
            ml_scores__category=self.category
        ).distinct()
        
        # Get compounds with user annotations
        user_annotated_compounds = Compound.objects.filter(
            usercompoundannotation__category=self.category,
            usercompoundannotation__is_verified=True
        ).distinct()
        
        # Combine both sets
        return (ml_scored_compounds | user_annotated_compounds).distinct()
    
    def get_training_labels(self, compounds: QuerySet) -> Dict[int, float]:
        """Get training labels for compounds"""
        labels = {}
        
        for compound in compounds:
            # Priority: verified user annotations > ML scores
            user_annotation = UserCompoundAnnotation.objects.filter(
                compound=compound,
                category=self.category,
                is_verified=True
            ).first()
            
            if user_annotation:
                labels[compound.id] = user_annotation.user_score
            else:
                ml_score = CompoundScore.objects.filter(
                    compound=compound,
                    category=self.category
                ).first()
                if ml_score:
                    labels[compound.id] = ml_score.score
        
        return labels
    
    def load_training_data(self) -> Tuple[np.ndarray, np.ndarray, List[int]]:
        """Load complete training dataset"""
        compounds = self.get_labeled_compounds()
        
        if compounds.count() < 10:
            raise ValueError(f"Insufficient training data for {self.category.name}: {compounds.count()} compounds")
        
        # Extract features
        X, compound_ids = self.feature_extractor.fit_transform(compounds)
        
        # Get labels
        label_dict = self.get_training_labels(compounds)
        y = np.array([label_dict.get(cid, 0.0) for cid in compound_ids])
        
        # Filter out compounds without labels
        valid_indices = [i for i, cid in enumerate(compound_ids) if cid in label_dict]
        X = X[valid_indices]
        y = y[valid_indices]
        compound_ids = [compound_ids[i] for i in valid_indices]
        
        return X, y, compound_ids
    
    def load_prediction_data(self, compounds: QuerySet) -> Tuple[np.ndarray, List[int]]:
        """Load data for prediction (no labels needed)"""
        if not self.feature_extractor.is_fitted:
            raise ValueError("Feature extractor must be fitted before prediction")
        
        return self.feature_extractor.transform(compounds)


def get_category_training_data(category_slug: str) -> Tuple[np.ndarray, np.ndarray, List[int], CompoundFeatureExtractor]:
    """Convenience function to get training data for a category"""
    try:
        category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
        loader = TrainingDataLoader(category)
        X, y, compound_ids = loader.load_training_data()
        return X, y, compound_ids, loader.feature_extractor
    except ScoringCategory.DoesNotExist:
        raise ValueError(f"Category '{category_slug}' not found or inactive")


def get_all_compound_features() -> Tuple[np.ndarray, List[int], CompoundFeatureExtractor]:
    """Get features for all compounds (for general-purpose models)"""
    compounds = Compound.objects.all()
    extractor = CompoundFeatureExtractor()
    X, compound_ids = extractor.fit_transform(compounds)
    return X, compound_ids, extractor
