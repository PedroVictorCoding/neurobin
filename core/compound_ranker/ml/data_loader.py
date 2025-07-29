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


class AdvancedCompoundFeatureExtractor:
    """Advanced feature extraction with chemical descriptors and embeddings"""
    
    def __init__(self):
        self.mechanism_encoder = None
        self.target_encoder = None
        self.action_encoder = None
        self.scaler = StandardScaler()
        self.tfidf_vectorizer = TfidfVectorizer(max_features=50, stop_words='english')
        self.feature_names = []
        self.is_fitted = False
        
        # Chemical feature extractors (would require RDKit in full implementation)
        self.chemical_features = [
            'molecular_weight', 'logp', 'hbd', 'hba', 'tpsa', 'rotatable_bonds',
            'aromatic_rings', 'heavy_atoms', 'formal_charge', 'complexity_score'
        ]
    
    def extract_chemical_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract chemical descriptors from SMILES (simplified version)"""
        features = []
        
        for compound in compounds:
            # Simplified chemical features based on available data
            feature_dict = {
                'compound_id': compound.id,
                'has_smiles': bool(compound.smiles),
                'smiles_length': len(compound.smiles) if compound.smiles else 0,
                'name_complexity': len(compound.name.split()) + len(compound.name),
                'has_chembl': bool(compound.chembl_id),
                'description_complexity': len(compound.description.split()) if compound.description else 0,
            }
            
            # Estimate chemical properties from name/description (heuristic)
            name_lower = compound.name.lower()
            desc_lower = (compound.description or '').lower()
            
            # Heuristic feature extraction
            feature_dict.update({
                'is_acid': 'acid' in name_lower or 'carbox' in name_lower,
                'is_amine': 'amine' in name_lower or 'amino' in name_lower,
                'is_steroid': 'steroid' in name_lower or 'sterone' in name_lower,
                'is_peptide': 'peptide' in name_lower or 'protein' in name_lower,
                'is_alkaloid': 'alkaloid' in name_lower or any(x in name_lower for x in ['ine', 'ide']),
                'has_phenol': 'phenol' in name_lower or 'hydroxy' in name_lower,
                'has_ketone': 'ketone' in name_lower or 'one' in name_lower,
                'molecular_complexity': len(set(name_lower)) * len(name_lower.split()),
            })
            
            features.append(feature_dict)
        
        return pd.DataFrame(features)
    
    def extract_mechanism_embeddings(self, compounds: QuerySet) -> pd.DataFrame:
        """Create embeddings from mechanism descriptions"""
        mechanism_texts = []
        compound_ids = []
        
        for compound in compounds:
            mechanisms = compound.mechanism_of_action.all()
            mechanism_text = []
            
            for mechanism in mechanisms:
                text_parts = []
                if mechanism.target_name:
                    text_parts.append(str(mechanism.target_name))
                if mechanism.target_interaction:
                    text_parts.append(mechanism.target_interaction)
                if mechanism.description:
                    text_parts.append(mechanism.description)
                
                if text_parts:
                    mechanism_text.append(' '.join(text_parts))
            
            # Combine all mechanism texts for this compound
            combined_text = ' '.join(mechanism_text) if mechanism_text else 'unknown mechanism'
            mechanism_texts.append(combined_text)
            compound_ids.append(compound.id)
        
        # Create TF-IDF features
        if not self.is_fitted:
            tfidf_features = self.tfidf_vectorizer.fit_transform(mechanism_texts)
        else:
            tfidf_features = self.tfidf_vectorizer.transform(mechanism_texts)
        
        # Convert to DataFrame
        feature_names = [f'mechanism_tfidf_{i}' for i in range(tfidf_features.shape[1])]
        tfidf_df = pd.DataFrame(
            tfidf_features.toarray(),
            columns=feature_names
        )
        tfidf_df['compound_id'] = compound_ids
        
        return tfidf_df
    
    def extract_pathway_features(self, compounds: QuerySet) -> pd.DataFrame:
        """Extract pathway and biological process features"""
        features = []
        
        # Define pathway keywords for different biological processes
        pathway_keywords = {
            'neurotransmission': ['dopamine', 'serotonin', 'acetylcholine', 'gaba', 'glutamate', 'norepinephrine'],
            'metabolism': ['glucose', 'lipid', 'fatty acid', 'glycolysis', 'krebs', 'oxidative'],
            'inflammation': ['cytokine', 'interleukin', 'tnf', 'cox', 'nf-kb', 'inflammatory'],
            'cell_cycle': ['apoptosis', 'proliferation', 'cell cycle', 'p53', 'mitosis'],
            'signaling': ['kinase', 'phosphatase', 'receptor', 'ligand', 'cascade', 'pathway'],
            'oxidative_stress': ['antioxidant', 'reactive oxygen', 'superoxide', 'catalase', 'glutathione'],
            'protein_synthesis': ['ribosome', 'translation', 'mrna', 'protein synthesis', 'elongation'],
            'dna_repair': ['dna repair', 'mutagenesis', 'damage', 'excision', 'recombination']
        }
        
        for compound in compounds:
            feature_dict = {'compound_id': compound.id}
            
            # Get all text associated with compound
            all_text = []
            all_text.append(compound.name.lower())
            if compound.description:
                all_text.append(compound.description.lower())
            
            # Add mechanism text
            for mechanism in compound.mechanism_of_action.all():
                if mechanism.target_name:
                    all_text.append(str(mechanism.target_name).lower())
                if mechanism.target_interaction:
                    all_text.append(mechanism.target_interaction.lower())
                if mechanism.description:
                    all_text.append(mechanism.description.lower())
            
            combined_text = ' '.join(all_text)
            
            # Score for each pathway
            for pathway, keywords in pathway_keywords.items():
                score = sum(1 for keyword in keywords if keyword in combined_text)
                feature_dict[f'pathway_{pathway}'] = score / len(keywords)  # Normalize
            
            features.append(feature_dict)
        
        return pd.DataFrame(features)
    
    def fit_transform(self, compounds: QuerySet) -> Tuple[np.ndarray, List[int]]:
        """Fit extractors and transform compounds to feature matrix"""
        compound_ids = list(compounds.values_list('id', flat=True))
        
        # Extract different feature types
        chemical_features = self.extract_chemical_features(compounds)
        mechanism_features = self.extract_mechanism_embeddings(compounds)
        pathway_features = self.extract_pathway_features(compounds)
        
        # Merge all features
        combined_features = chemical_features.merge(
            mechanism_features, on='compound_id', how='left'
        ).merge(
            pathway_features, on='compound_id', how='left'
        )
        
        # Fill NaN values
        combined_features = combined_features.fillna(0)
        
        # Remove compound_id for feature matrix
        feature_matrix = combined_features.drop('compound_id', axis=1)
        
        # Scale features
        if not self.is_fitted:
            scaled_features = self.scaler.fit_transform(feature_matrix)
            self.feature_names = list(feature_matrix.columns)
            self.is_fitted = True
        else:
            scaled_features = self.scaler.transform(feature_matrix)
        
        return scaled_features, compound_ids
    
    def transform(self, compounds: QuerySet) -> Tuple[np.ndarray, List[int]]:
        """Transform compounds using fitted extractors"""
        if not self.is_fitted:
            raise ValueError("Feature extractor must be fitted before transform")
        
        return self.fit_transform(compounds)


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
        features = []
        for compound in compounds:
            # Get interactions for this compound
            interactions = CompoundTargetInteraction.objects.filter(compound=compound)
            # Aggregate interaction features
            feature_dict = {
                'compound_id': compound.id,
                'total_interactions': interactions.count(),
                'unique_targets': interactions.values('target').distinct().count(),
            }
            # Affinity level counts (categorical encoding)
            affinity_levels = ['very_high', 'high', 'medium', 'low', 'very_low', 'unknown']
            affinity_counts = dict.fromkeys(affinity_levels, 0)
            for level in interactions.values_list('affinity_level', flat=True):
                if level in affinity_counts:
                    affinity_counts[level] += 1
            for level in affinity_levels:
                feature_dict[f'affinity_count_{level}'] = affinity_counts[level]
            # Target type distribution
            target_types = interactions.values_list('target__target_type', flat=True)
            for target_type, _ in Target.TARGET_TYPES:
                feature_dict[f'target_type_{target_type}'] = list(target_types).count(target_type)
            # Action type distribution (use structured_action_type__name)
            action_types = interactions.values_list('structured_action_type__name', flat=True)
            for action_type in ActionType.objects.all():
                feature_dict[f'action_type_{action_type.name}'] = list(action_types).count(action_type.name)
            # Mechanism distribution (mechanism is a CharField, not FK)
            mechanisms = interactions.values_list('mechanism', flat=True)
            for mech_value, _ in CompoundTargetInteraction.MECHANISM_CHOICES:
                feature_dict[f'mechanism_{mech_value}'] = list(mechanisms).count(mech_value)
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
