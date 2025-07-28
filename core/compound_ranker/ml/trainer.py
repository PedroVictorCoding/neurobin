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

from compound_ranker.models import ScoringCategory, ModelTrainingLog
from .data_loader import get_category_training_data, CompoundFeatureExtractor

logger = logging.getLogger(__name__)


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


class CompoundTrainer:
    """Trainer for compound scoring models"""
    
    def __init__(self, category: ScoringCategory, model_version: str = None):
        self.category = category
        self.model_version = model_version or f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.model = None
        self.feature_extractor = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Create model directory
        self.model_dir = os.path.join(settings.BASE_DIR, 'ml_models', 'compound_ranker')
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Initialize training log
        self.training_log = None
    
    def create_training_log(self, user: User = None) -> ModelTrainingLog:
        """Create training log entry"""
        self.training_log = ModelTrainingLog.objects.create(
            category=self.category,
            model_version=self.model_version,
            training_started=datetime.now(),
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
                training_completed=datetime.now()
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
    
    def train_model(self, epochs: int = 100, learning_rate: float = 0.001, user: User = None) -> Dict:
        """Train the model"""
        # Create training log
        self.create_training_log(user)
        
        try:
            # Prepare data
            train_loader, val_loader, test_loader = self.prepare_data()
            
            # Get input size from first batch
            first_batch = next(iter(train_loader))
            input_size = first_batch[0].shape[1]
            
            # Create model
            hyperparams = {
                'hidden_sizes': [256, 128, 64],
                'dropout_rate': 0.3,
                'learning_rate': learning_rate,
                'epochs': epochs
            }
            
            self.model = self.create_model(input_size, hyperparams)
            
            # Loss function and optimizer
            criterion = nn.MSELoss()
            optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
            
            # Training loop
            train_losses = []
            val_losses = []
            best_val_loss = float('inf')
            
            for epoch in range(epochs):
                # Training
                self.model.train()
                train_loss = 0.0
                
                for batch_x, batch_y in train_loader:
                    batch_x, batch_y = batch_x.to(self.device), batch_y.to(self.device)
                    
                    optimizer.zero_grad()
                    outputs = self.model(batch_x)
                    
                    # We only use the score (first output) for training
                    # The confidence will be estimated based on prediction uncertainty
                    loss = criterion(outputs[:, 0], batch_y)
                    loss.backward()
                    optimizer.step()
                    
                    train_loss += loss.item()
                
                train_loss /= len(train_loader)
                train_losses.append(train_loss)
                
                # Validation
                self.model.eval()
                val_loss = 0.0
                
                with torch.no_grad():
                    for batch_x, batch_y in val_loader:
                        batch_x, batch_y = batch_x.to(self.device), batch_y.to(self.device)
                        outputs = self.model(batch_x)
                        loss = criterion(outputs[:, 0], batch_y)
                        val_loss += loss.item()
                
                val_loss /= len(val_loader)
                val_losses.append(val_loss)
                
                # Learning rate scheduling
                scheduler.step(val_loss)
                
                # Save best model
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    self.save_model()
                
                if epoch % 10 == 0:
                    logger.info(f"Epoch {epoch}: Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}")
            
            # Final evaluation
            test_metrics = self.evaluate_model(test_loader)
            
            # Update training log
            self.update_training_log(
                status='completed',
                training_completed=datetime.now(),
                validation_accuracy=test_metrics['r2_score'],
                validation_loss=best_val_loss,
                hyperparameters=hyperparams
            )
            
            logger.info(f"Training completed for {self.category.name}")
            logger.info(f"Final metrics: {test_metrics}")
            
            return {
                'train_losses': train_losses,
                'val_losses': val_losses,
                'test_metrics': test_metrics,
                'model_path': self.get_model_path()
            }
            
        except Exception as e:
            self.update_training_log(
                status='failed',
                error_message=str(e),
                training_completed=datetime.now()
            )
            logger.error(f"Training failed for {self.category.name}: {str(e)}")
            raise
    
    def evaluate_model(self, test_loader: DataLoader) -> Dict:
        """Evaluate model performance"""
        self.model.eval()
        y_true = []
        y_pred = []
        
        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x, batch_y = batch_x.to(self.device), batch_y.to(self.device)
                outputs = self.model(batch_x)
                
                y_true.extend(batch_y.cpu().numpy())
                y_pred.extend(outputs[:, 0].cpu().numpy())  # Score predictions
        
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        
        metrics = {
            'mse': mean_squared_error(y_true, y_pred),
            'mae': mean_absolute_error(y_true, y_pred),
            'r2_score': r2_score(y_true, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_true, y_pred))
        }
        
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
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'category_slug': self.category.slug,
            'model_version': self.model_version,
            'input_size': next(self.model.parameters()).shape[1] if self.model else None
        }, self.get_model_path())
        
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
            input_size = checkpoint.get('input_size', 100)  # Default fallback
            
            self.model = self.create_model(input_size)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.model.eval()
        
        # Load feature extractor
        if os.path.exists(extractor_path):
            with open(extractor_path, 'rb') as f:
                self.feature_extractor = pickle.load(f)


def train_category_model(category_slug: str, epochs: int = 100, user: User = None) -> Dict:
    """Train model for a specific category"""
    try:
        category = ScoringCategory.objects.get(slug=category_slug, is_active=True)
        trainer = CompoundTrainer(category)
        return trainer.train_model(epochs=epochs, user=user)
    except ScoringCategory.DoesNotExist:
        raise ValueError(f"Category '{category_slug}' not found or inactive")


def train_all_models(epochs: int = 100, user: User = None) -> Dict[str, Dict]:
    """Train models for all active categories"""
    results = {}
    categories = ScoringCategory.objects.filter(is_active=True)
    
    for category in categories:
        try:
            logger.info(f"Training model for {category.name}")
            trainer = CompoundTrainer(category)
            result = trainer.train_model(epochs=epochs, user=user)
            results[category.slug] = result
        except Exception as e:
            logger.error(f"Failed to train model for {category.name}: {str(e)}")
            results[category.slug] = {'error': str(e)}
    
    return results
