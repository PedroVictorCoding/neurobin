# Compound Ranker Setup Guide

## Initial Setup

After installing the compound_ranker app, you need to run the following commands to set up the system:

### 1. Run Migrations
```bash
python manage.py migrate
```

### 2. Initialize Scoring Categories
```bash
python manage.py init_categories
```

This will create the default 14 scoring categories:
- Longevity-enhancing
- Cognitive enhancer
- Anabolic
- Neuroprotective
- Cardioprotective
- Liver-protective
- Mitochondrial enhancer
- Anti-inflammatory
- Metabolic stabilizer
- Immunomodulator
- Psychostimulant
- Mood enhancer
- Stress resilience
- Nootropic

### 3. Generate Test Scores (Optional)
If you want to populate the system with sample scores for testing:
```bash
python manage.py generate_test_scores --limit 20
```

### 4. Train ML Models (Optional)
To use the advanced ML ranking features, install ML dependencies first:
```bash
pip install -r ml_requirements.txt
```

Then train models:
```bash
# Train models for all categories
python manage.py train_advanced_model --all-categories

# Or train for specific category
python manage.py train_advanced_model --category longevity
```

### 5. Generate ML Predictions (Optional)
After training models:
```bash
# Enhanced ensemble predictions
python manage.py predict_enhanced --all-categories

# Standard predictions
python manage.py predict_scores --all-categories
```

## Troubleshooting

### Database Access Warning
If you see a warning about "Accessing the database during app initialization", it means the app is trying to access the database during Django startup. This has been fixed by removing database access from the `AppConfig.ready()` method.

### Missing Categories
If the ranking pages show no categories, run:
```bash
python manage.py init_categories
```

### No Scores Available
If compounds have no scores, either:
1. Generate test scores: `python manage.py generate_test_scores`
2. Train and run ML models (see steps 4-5 above)

## Usage

Once set up, the compound ranker will be available at:
- `/rankings/` - Main rankings page
- `/rankings/<category-slug>/` - Category-specific rankings
- `/compound-detail/<compound-id>/` - Individual compound scores

Admin users can access:
- Training status monitoring
- Category management
- Model training controls
