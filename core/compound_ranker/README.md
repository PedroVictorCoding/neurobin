# 🧠 Compound Ranker

A Django app that uses neural networks to score and rank compounds across customizable health-focused categories like longevity, cognition, anabolism, and organ protection.

## Features

- **Neural Network Scoring**: Uses PyTorch-based models to score compounds
- **Multiple Categories**: 14 predefined health categories (longevity, cognition, etc.)
- **Fallback Scoring**: Works even without ML dependencies using mechanism-based scoring
- **RESTful API**: Complete API for integration with other tools
- **Admin Interface**: Django admin integration for managing categories and scores
- **User Annotations**: Allow users to provide feedback to improve models
- **Export Functionality**: CSV export of rankings
- **Responsive UI**: Mobile-friendly web interface

## Categories

| Category | Description |
|----------|-------------|
| Longevity | Compounds that may improve lifespan markers |
| Cognitive enhancer | Improves memory, attention, and cognitive function |
| Anabolic | Increases lean mass or muscle protein synthesis |
| Neuroprotective | Prevents neurodegeneration and protects brain health |
| Cardioprotective | Supports cardiovascular health |
| Liver-protective | Reduces liver toxicity or damage |
| Mitochondrial enhancer | Boosts energy metabolism |
| Anti-inflammatory | Reduces inflammatory markers |
| Metabolic stabilizer | Improves insulin sensitivity |
| Immunomodulator | Supports immune system balance |
| Psychostimulant | Increases alertness and focus |
| Mood enhancer | Positively affects mood and well-being |
| Stress resilience | Adaptogenic effects for stress management |
| Nootropic | Broad cognitive support |

## Installation

1. **Add to Django settings**:
   ```python
   INSTALLED_APPS = [
       # ... other apps
       'compound_ranker',
   ]
   ```

2. **Add to URLs**:
   ```python
   urlpatterns = [
       # ... other patterns
       path('rankings/', include('compound_ranker.urls')),
       path('api/rankings/', include('compound_ranker.api.urls')),
   ]
   ```

3. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

4. **Initialize categories**:
   ```bash
   python manage.py init_categories
   ```

5. **Optional: Install ML dependencies**:
   ```bash
   pip install -r ml_requirements.txt
   ```

## Usage

### Basic Scoring (Fallback Mode)

The app works out of the box with a fallback scoring system based on compound mechanisms:

```bash
# Generate scores for all compounds
python manage.py predict_scores

# Generate scores for specific category
python manage.py predict_scores --category=longevity

# Generate scores for specific compound
python manage.py predict_scores --compound="Resveratrol"
```

### Advanced ML Training

If you have ML dependencies installed:

```bash
# Train models for all categories
python manage.py train_model

# Train model for specific category
python manage.py train_model --category=longevity --epochs=100

# Train with user attribution
python manage.py train_model --user=admin
```

### Web Interface

- **View all categories**: `/rankings/`
- **Category rankings**: `/rankings/{category_slug}/`
- **Compound details**: `/rankings/compound/{compound_id}/`
- **Training status**: `/rankings/training-status/` (staff only)

### API Endpoints

- `GET /api/rankings/categories/` - List all categories
- `GET /api/rankings/compound-scores/` - List compound scores
- `GET /api/rankings/top-compounds/?category=longevity&n=10` - Top compounds
- `GET /api/rankings/compounds/{id}/rankings/` - Compound across categories
- `POST /api/rankings/annotations/` - Add user annotation

## Model Architecture

### Input Features

- Mechanisms of action (multi-hot encoding)
- Target classes (receptor, enzyme, transporter)
- Interaction data (affinity scores, target counts)
- Compound metadata (ChEMBL ID, view count, etc.)
- Text features (TF-IDF from descriptions)

### Model Structure

```python
class CompoundScoringNet(nn.Module):
    def __init__(self, input_size, hidden_sizes=[256, 128, 64]):
        # Multi-layer neural network
        # Output: [score, confidence] both in range [0, 1]
```

### Training Data

- Existing compound scores (if available)
- Verified user annotations
- Minimum 10 compounds required per category

## Fallback Scoring

When ML models aren't available, the system uses:

1. **Base score** per category (0.1-0.4)
2. **Mechanism matching** (+0.15 per relevant mechanism)
3. **Interaction data** (+0.01 per interaction, up to 0.2)
4. **Data quality** (+0.1 for ChEMBL ID)
5. **Popularity** (+0.001 per view, up to 0.1)

## Admin Features

### Django Admin Integration

- **Category Management**: Add/edit scoring categories
- **Score Visualization**: Color-coded score bars and confidence indicators
- **Training Logs**: View model training history and performance
- **User Annotations**: Manage and verify user contributions

### Staff Views

- Training status dashboard
- Model performance metrics
- Export functionality
- Bulk operations

## API Examples

### Get Top Longevity Compounds

```bash
curl "http://localhost:8000/api/rankings/top-compounds/?category=longevity&n=5"
```

```json
{
  "category": {
    "name": "Longevity-enhancing",
    "slug": "longevity",
    "description": "Compounds that may improve lifespan markers"
  },
  "compounds": [
    {
      "compound": {
        "name": "Resveratrol",
        "chembl_id": "CHEMBL15"
      },
      "score": 0.87,
      "confidence": 0.92,
      "rank_in_category": 1
    }
  ],
  "total_count": 150,
  "limit": 5
}
```

### Add User Annotation

```bash
curl -X POST "http://localhost:8000/api/rankings/annotations/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "compound": 1,
    "category": 1,
    "user_score": 0.9,
    "notes": "Strong longevity evidence from studies"
  }'
```

## Development

### Running Tests

```bash
python manage.py test compound_ranker
```

### Adding New Categories

```python
from compound_ranker.models import ScoringCategory

category = ScoringCategory.objects.create(
    name="New Category",
    slug="new_category",
    description="Description of the new category",
    icon="🔬"
)
```

### Custom Scoring Logic

Extend the `CompoundPredictor` class to implement custom scoring:

```python
from compound_ranker.ml.predictor import CompoundPredictor

class CustomPredictor(CompoundPredictor):
    def _fallback_predict(self, compound):
        # Custom scoring logic
        return score, confidence
```

## Performance Considerations

- **Database Indexes**: Added on frequently queried fields
- **Caching**: Model and feature extractor caching
- **Batch Processing**: Efficient bulk predictions
- **Pagination**: Large result sets are paginated

## Security

- **Authentication**: Required for user annotations
- **Staff Only**: Model training and sensitive operations
- **Validation**: Input validation on all API endpoints
- **Rate Limiting**: Consider adding for production

## Troubleshooting

### Common Issues

1. **ML Dependencies Missing**: App falls back to rule-based scoring
2. **Insufficient Training Data**: Need minimum 10 compounds per category
3. **Memory Issues**: Reduce batch size or use CPU instead of GPU

### Debug Commands

```bash
# Check categories
python manage.py shell -c "from compound_ranker.models import ScoringCategory; print(ScoringCategory.objects.all())"

# Test prediction
python manage.py predict_scores --compound="Caffeine" --category=cognition

# View training logs
python manage.py shell -c "from compound_ranker.models import ModelTrainingLog; print(ModelTrainingLog.objects.all())"
```

## Future Enhancements

- [ ] Structure-based similarity scoring
- [ ] Multi-modal learning (text + structure)
- [ ] Uncertainty quantification
- [ ] A/B testing for model versions
- [ ] Real-time model updates
- [ ] Integration with chemical databases
- [ ] Advanced visualization dashboards

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

This project is part of the Neurobin platform and follows the same licensing terms.
