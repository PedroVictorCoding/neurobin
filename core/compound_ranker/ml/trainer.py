"""
Neural network trainer for compound scoring models
"""
import os
import pickle
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from compound_ranker.models import ScoringCategory, ModelTrainingLog
from .data_loader import get_category_training_data, CompoundFeatureExtractor

logger = logging.getLogger(__name__)


class AdvancedCompoundScoringNet(nn.Module):
    """Enhanced neural network for compound scoring with attention and residual connections"""
    
    def __init__(self, input_size: int, hidden_sizes: List[int] = None, dropout_rate: float = 0.3):
        super(AdvancedCompoundScoringNet, self).__init__()
        
        if hidden_sizes is None:
            hidden_sizes = [512, 256, 128, 64]
        
        # Feature attention mechanism
        self.feature_attention = nn.Sequential(
            nn.Linear(input_size, input_size // 4),
            nn.ReLU(),
            nn.Linear(input_size // 4, input_size),
            nn.Sigmoid()
        )
        
        # Main processing layers with residual connections
        self.layers = nn.ModuleList()
        prev_size = input_size
        
        for i, hidden_size in enumerate(hidden_sizes):
            # Main layer
            layer = nn.Sequential(
                nn.Linear(prev_size, hidden_size),
                nn.BatchNorm1d(hidden_size),
                nn.ReLU(),
                nn.Dropout(dropout_rate)
            )
            self.layers.append(layer)
            
            # Residual connection (if dimensions match)
            if prev_size == hidden_size:
                setattr(self, f'residual_{i}', nn.Identity())
            else:
                setattr(self, f'residual_{i}', nn.Linear(prev_size, hidden_size))
            
            prev_size = hidden_size
        
        # Multi-head output with uncertainty estimation
        self.score_head = nn.Sequential(
            nn.Linear(prev_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout_rate * 0.5),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )
        
        self.confidence_head = nn.Sequential(
            nn.Linear(prev_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout_rate * 0.5),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )
        
        # Uncertainty estimation head
        self.uncertainty_head = nn.Sequential(
            nn.Linear(prev_size, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Softplus()  # Ensures positive uncertainty
        )
    
    def forward(self, x):
        # Apply feature attention
        attention_weights = self.feature_attention(x)
        x_attended = x * attention_weights
        
        # Forward through main layers with residual connections
        current = x_attended
        for i, layer in enumerate(self.layers):
            residual_layer = getattr(self, f'residual_{i}')
            
            # Apply main transformation
            transformed = layer(current)
            
            # Add residual connection
            residual = residual_layer(current)
            current = transformed + residual
        
        # Multi-head outputs
        score = self.score_head(current)
        confidence = self.confidence_head(current)
        uncertainty = self.uncertainty_head(current)
        
        return torch.cat([score, confidence, uncertainty], dim=1)


class CompoundScoringNet(nn.Module):
    """Neural network for compound scoring"""
    
    def __init__(self, input_size: int, hidden_sizes: List[int] = None, dropout_rate: float = 0.3):
        super(CompoundScoringNet, self).__init__()
        
        if hidden_sizes is None:
            hidden_sizes = [256, 128, 64]
        
        layers = []
        prev_size = input_size
        
        for hidden_size in hidden_sizes:
            layers.append(nn.Linear(prev_size, hidden_size))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout_rate))
            prev_size = hidden_size
        
        # Output layer: score and confidence
        layers.append(nn.Linear(prev_size, 2))
        layers.append(nn.Sigmoid())  # Both score and confidence in [0, 1]
        
        self.network = nn.Sequential(*layers)
    
    def forward(self, x):
        return self.network(x)


class UncertaintyAwareLoss(nn.Module):
    """Advanced loss function that accounts for prediction uncertainty"""
    
    def __init__(self, alpha=1.0, beta=0.5, gamma=0.1):
        super(UncertaintyAwareLoss, self).__init__()
        self.alpha = alpha  # Score loss weight
        self.beta = beta    # Confidence loss weight
        self.gamma = gamma  # Uncertainty regularization weight
        
    def forward(self, predictions, targets, sample_weights=None):
        """
        predictions: [batch_size, 3] (score, confidence, uncertainty)
        targets: [batch_size, 2] (score, confidence)
        """
        pred_score = predictions[:, 0]
        pred_confidence = predictions[:, 1]
        pred_uncertainty = predictions[:, 2]
        
        target_score = targets[:, 0]
        target_confidence = targets[:, 1]
        
        # Score loss weighted by predicted confidence
        score_loss = torch.mean(pred_confidence * (pred_score - target_score) ** 2)
        
        # Confidence loss
        confidence_loss = torch.mean((pred_confidence - target_confidence) ** 2)
        
        # Uncertainty regularization (encourage calibrated uncertainty)
        uncertainty_reg = torch.mean(pred_uncertainty ** 2)
        
        # Combine losses
        total_loss = (self.alpha * score_loss + 
                     self.beta * confidence_loss + 
                     self.gamma * uncertainty_reg)
        
        if sample_weights is not None:
            total_loss = torch.mean(sample_weights * total_loss)
        
        return total_loss, {
            'score_loss': score_loss.item(),
            'confidence_loss': confidence_loss.item(),
            'uncertainty_reg': uncertainty_reg.item()
        }


class CompoundTrainer:
    """Enhanced trainer for compound scoring models"""
    
    def __init__(self, category: ScoringCategory, model_version: str = None, use_advanced_model: bool = True):
        self.category = category
        self.model_version = model_version or f"v{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        self.model = None
        self.feature_extractor = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.use_advanced_model = use_advanced_model
        
        # Create model directory
        self.model_dir = os.path.join(settings.BASE_DIR, 'ml_models', 'compound_ranker')
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Initialize training log
        self.training_log = None
        
        # Training hyperparameters
        self.hyperparameters = {
            'learning_rate': 0.001,
            'batch_size': 32,
            'epochs': 150,
            'patience': 20,
            'weight_decay': 1e-5,
            'lr_scheduler_factor': 0.5,
            'lr_scheduler_patience': 10
        }
    
    def create_training_log(self, user: User = None) -> ModelTrainingLog:
        """Create training log entry"""
        self.training_log = ModelTrainingLog.objects.create(
            category=self.category,
            model_version=self.model_version,
            training_started=timezone.now(),
            status='running',
            trained_by=user
        )
        return self.training_log
    
    def update_training_log(self, **kwargs):
        """Update training log"""
        if self.training_log:
            for key, value in kwargs.items():
                setattr(self.training_log, key, value)
            self.training_log.save()
    
    def prepare_data(self) -> Tuple[DataLoader, DataLoader, DataLoader]:
        """Prepare training, validation, and test data loaders"""
        try:
            X, y, compound_ids, feature_extractor = get_category_training_data(self.category.slug)
            self.feature_extractor = feature_extractor
            
            logger.info(f"Loaded {len(X)} training samples for {self.category.name}")
            
            # Split data
            X_train, X_temp, y_train, y_temp = train_test_split(
                X, y, test_size=0.3, random_state=42, stratify=None
            )
            X_val, X_test, y_val, y_test = train_test_split(
                X_temp, y_temp, test_size=0.5, random_state=42
            )
            
            # Convert to PyTorch tensors
            X_train_tensor = torch.FloatTensor(X_train)
            y_train_tensor = torch.FloatTensor(y_train)
            X_val_tensor = torch.FloatTensor(X_val)
            y_val_tensor = torch.FloatTensor(y_val)
            X_test_tensor = torch.FloatTensor(X_test)
            y_test_tensor = torch.FloatTensor(y_test)
            
            # Create data loaders
            train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
            val_dataset = TensorDataset(X_val_tensor, y_val_tensor)
            test_dataset = TensorDataset(X_test_tensor, y_test_tensor)
            
            train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
            val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)
            test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)
            
            # Update training log
            self.update_training_log(
                training_samples=len(X_train),
                hyperparameters={
                    'train_size': len(X_train),
                    'val_size': len(X_val),
                    'test_size': len(X_test),
                    'input_features': X.shape[1]
                }
            )
            
            return train_loader, val_loader, test_loader
            
        except Exception as e:
            self.update_training_log(
                status='failed',
                error_message=str(e),
                training_completed=timezone.now()
            )
            raise
    
    def create_model(self, input_size: int, hyperparams: Dict = None) -> CompoundScoringNet:
        """Create and initialize model"""
        if hyperparams is None:
            hyperparams = {
                'hidden_sizes': [256, 128, 64],
                'dropout_rate': 0.3
            }
        
        model = CompoundScoringNet(
            input_size=input_size,
            hidden_sizes=hyperparams.get('hidden_sizes', [256, 128, 64]),
            dropout_rate=hyperparams.get('dropout_rate', 0.3)
        )
        
        model.to(self.device)
        return model
    
    def train_model(self, epochs: int = None, learning_rate: float = None, user: User = None) -> Dict:
        """Enhanced training with advanced techniques"""
        try:
            # Use hyperparameters if not provided
            epochs = epochs or self.hyperparameters['epochs']
            learning_rate = learning_rate or self.hyperparameters['learning_rate']
            
            # Create training log
            self.create_training_log(user)
            
            # Prepare data
            train_loader, val_loader, test_loader = self.prepare_data()
            
            if not train_loader:
                raise ValueError("No training data available")
            
            # Get input size from first batch
            X_sample, _ = next(iter(train_loader))
            input_size = X_sample.shape[1]
            
            # Initialize model
            if self.use_advanced_model:
                self.model = AdvancedCompoundScoringNet(input_size).to(self.device)
                output_size = 3  # score, confidence, uncertainty
            else:
                self.model = CompoundScoringNet(input_size).to(self.device)
                output_size = 2  # score, confidence
            
            # Advanced optimization setup
            optimizer = optim.AdamW(
                self.model.parameters(), 
                lr=learning_rate,
                weight_decay=self.hyperparameters['weight_decay']
            )
            
            # Learning rate scheduler
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(
                optimizer, 
                mode='min',
                factor=self.hyperparameters['lr_scheduler_factor'],
                patience=self.hyperparameters['lr_scheduler_patience'],
                verbose=True
            )
            
            # Loss function
            if self.use_advanced_model:
                criterion = UncertaintyAwareLoss()
            else:
                criterion = nn.MSELoss()
            
            # Training tracking
            best_val_loss = float('inf')
            patience_counter = 0
            training_history = {
                'train_losses': [], 'val_losses': [], 'learning_rates': [],
                'score_losses': [], 'confidence_losses': [], 'uncertainty_regs': []
            }
            
            logger.info(f"Starting enhanced training for {self.category.name} model...")
            
            for epoch in range(epochs):
                # Training phase
                self.model.train()
                train_loss = 0.0
                train_metrics = {'score_loss': 0, 'confidence_loss': 0, 'uncertainty_reg': 0}
                
                for batch_idx, (X_batch, y_batch) in enumerate(train_loader):
                    X_batch, y_batch = X_batch.to(self.device), y_batch.to(self.device)
                    
                    optimizer.zero_grad()
                    
                    # Forward pass
                    outputs = self.model(X_batch)
                    
                    # Calculate loss
                    if self.use_advanced_model:
                        loss, batch_metrics = criterion(outputs, y_batch)
                        for key, value in batch_metrics.items():
                            train_metrics[key] += value
                    else:
                        loss = criterion(outputs, y_batch)
                    
                    # Backward pass
                    loss.backward()
                    
                    # Gradient clipping for stability
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                    
                    optimizer.step()
                    train_loss += loss.item()
                
                # Validation phase
                self.model.eval()
                val_loss = 0.0
                val_metrics = {'score_loss': 0, 'confidence_loss': 0, 'uncertainty_reg': 0}
                
                with torch.no_grad():
                    for X_batch, y_batch in val_loader:
                        X_batch, y_batch = X_batch.to(self.device), y_batch.to(self.device)
                        outputs = self.model(X_batch)
                        
                        if self.use_advanced_model:
                            loss, batch_metrics = criterion(outputs, y_batch)
                            for key, value in batch_metrics.items():
                                val_metrics[key] += value
                        else:
                            loss = criterion(outputs, y_batch)
                        
                        val_loss += loss.item()
                
                # Calculate average losses
                avg_train_loss = train_loss / len(train_loader)
                avg_val_loss = val_loss / len(val_loader)
                
                # Update learning rate
                scheduler.step(avg_val_loss)
                current_lr = optimizer.param_groups[0]['lr']
                
                # Store training history
                training_history['train_losses'].append(avg_train_loss)
                training_history['val_losses'].append(avg_val_loss)
                training_history['learning_rates'].append(current_lr)
                
                if self.use_advanced_model:
                    for key in train_metrics:
                        training_history[f'{key}s'].append(train_metrics[key] / len(train_loader))
                
                # Early stopping check
                if avg_val_loss < best_val_loss:
                    best_val_loss = avg_val_loss
                    patience_counter = 0
                    # Save best model
                    self.save_model()
                else:
                    patience_counter += 1
                
                # Logging
                if epoch % 10 == 0 or patience_counter == 0:
                    logger.info(
                        f"Epoch {epoch:3d} | Train Loss: {avg_train_loss:.4f} | "
                        f"Val Loss: {avg_val_loss:.4f} | LR: {current_lr:.6f}"
                    )
                
                # Early stopping
                if patience_counter >= self.hyperparameters['patience']:
                    logger.info(f"Early stopping at epoch {epoch}")
                    break
            
            # Final evaluation on test set
            test_metrics = self.evaluate_model(test_loader)
            
            # Update training log
            self.update_training_log(
                training_completed=timezone.now(),
                status='completed',
                final_metrics=test_metrics,
                training_history=training_history,
                hyperparameters=self.hyperparameters
            )
            
            logger.info(f"Training completed for {self.category.name}")
            return {
                'success': True,
                'test_metrics': test_metrics,
                'training_history': training_history,
                'model_path': self.get_model_path()
            }
            
        except Exception as e:
            error_msg = f"Training failed: {str(e)}"
            logger.error(error_msg)
            
            if self.training_log:
                self.update_training_log(
                    status='failed',
                    error_message=error_msg
                )
            
            return {'success': False, 'error': error_msg}
    
    def evaluate_model(self, test_loader: DataLoader) -> Dict:
        """Comprehensive model evaluation"""
        self.model.eval()
        all_predictions = []
        all_targets = []
        
        with torch.no_grad():
            for X_batch, y_batch in test_loader:
                X_batch = X_batch.to(self.device)
                outputs = self.model(X_batch)
                
                all_predictions.append(outputs.cpu().numpy())
                all_targets.append(y_batch.numpy())
        
        predictions = np.vstack(all_predictions)
        targets = np.vstack(all_targets)
        
        # Calculate metrics
        metrics = {}
        
        # Score metrics
        score_predictions = predictions[:, 0]
        score_targets = targets[:, 0]
        
        metrics['score_mse'] = mean_squared_error(score_targets, score_predictions)
        metrics['score_mae'] = mean_absolute_error(score_targets, score_predictions)
        metrics['score_r2'] = r2_score(score_targets, score_predictions)
        
        # Confidence metrics
        confidence_predictions = predictions[:, 1]
        confidence_targets = targets[:, 1]
        
        metrics['confidence_mse'] = mean_squared_error(confidence_targets, confidence_predictions)
        metrics['confidence_mae'] = mean_absolute_error(confidence_targets, confidence_predictions)
        
        # Uncertainty metrics (if available)
        if predictions.shape[1] > 2:
            uncertainty_predictions = predictions[:, 2]
            metrics['avg_uncertainty'] = np.mean(uncertainty_predictions)
            metrics['uncertainty_std'] = np.std(uncertainty_predictions)
        
        # Ranking metrics
        score_rank_corr = np.corrcoef(score_targets, score_predictions)[0, 1]
        metrics['ranking_correlation'] = score_rank_corr if not np.isnan(score_rank_corr) else 0.0
        
        return metrics
    
    def get_model_path(self) -> str:
        """Get path for saving model"""
        return os.path.join(
            self.model_dir,
            f"{self.category.slug}_{self.model_version}.pth"
        )
    
    def get_feature_extractor_path(self) -> str:
        """Get path for saving feature extractor"""
        return os.path.join(
            self.model_dir,
            f"{self.category.slug}_{self.model_version}_extractor.pkl"
        )
    
    def save_model(self):
        """Save model and feature extractor"""
        # Save PyTorch model
        model_data = {
            'model_state_dict': self.model.state_dict(),
            'category_slug': self.category.slug,
            'model_version': self.model_version,
            'model_type': 'advanced' if self.use_advanced_model else 'standard',
            'hyperparameters': self.hyperparameters
        }
        
        # Get input size from model
        if hasattr(self.model, 'feature_attention'):
            # Advanced model
            input_size = self.model.feature_attention[0].in_features
        else:
            # Standard model
            input_size = self.model.network[0].in_features
        
        model_data['input_size'] = input_size
        
        torch.save(model_data, self.get_model_path())
        
        # Save feature extractor
        if self.feature_extractor:
            with open(self.get_feature_extractor_path(), 'wb') as f:
                pickle.dump(self.feature_extractor, f)
    
    def load_model(self, model_path: str = None, extractor_path: str = None):
        """Load trained model and feature extractor"""
        if model_path is None:
            model_path = self.get_model_path()
        if extractor_path is None:
            extractor_path = self.get_feature_extractor_path()
        
        # Load model
        if os.path.exists(model_path):
            checkpoint = torch.load(model_path, map_location=self.device)
            
            input_size = checkpoint.get('input_size', 100)
            model_type = checkpoint.get('model_type', 'standard')
            
            # Initialize correct model type
            if model_type == 'advanced':
                self.model = AdvancedCompoundScoringNet(input_size).to(self.device)
                self.use_advanced_model = True
            else:
                self.model = CompoundScoringNet(input_size).to(self.device)
                self.use_advanced_model = False
            
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.model.eval()
            
            # Load hyperparameters if available
            if 'hyperparameters' in checkpoint:
                self.hyperparameters.update(checkpoint['hyperparameters'])
        
        # Load feature extractor
        if os.path.exists(extractor_path):
            with open(extractor_path, 'rb') as f:
                self.feature_extractor = pickle.load(f)


def train_category_model(category_slug: str, epochs: int = None, user: User = None, use_advanced: bool = True) -> Dict:
    """Train model for a specific category"""
    try:
        category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
        trainer = CompoundTrainer(category, use_advanced_model=use_advanced)
        return trainer.train_model(epochs=epochs, user=user)
    except ScoringCategory.DoesNotExist:
        raise ValueError(f"Category '{category_slug}' not found or inactive")


def train_all_models(epochs: int = None, user: User = None, use_advanced: bool = True) -> Dict[str, Dict]:
    """Train models for all active categories"""
    results = {}
    categories = ScoringCategory.objects.filter(is_active=True)
    
    for category in categories:
        try:
            logger.info(f"Training model for {category.name}")
            trainer = CompoundTrainer(category, use_advanced_model=use_advanced)
            result = trainer.train_model(epochs=epochs, user=user)
            results[category.slug] = result
        except Exception as e:
            logger.error(f"Failed to train model for {category.name}: {str(e)}")
            results[category.slug] = {'success': False, 'error': str(e)}
    
    return results
