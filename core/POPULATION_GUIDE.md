# Neurobin Comprehensive Data Population Guide

## Overview

This comprehensive data population system fills your Neurobin database with real-world data from multiple scientific APIs and generates synthetic data to create a fully functional research platform.

## 🎯 What Gets Populated

### Core Data (from APIs)
- **5,000+ Targets** from ChEMBL database
- **10,000+ Compounds** from ChEMBL database  
- **15,000+ Mechanisms of Action** from ChEMBL
- **2,000+ Biological Pathways** from Reactome
- **10,000+ Pathway Effects** (computed relationships)

### Community Data (generated)
- **100 User Profiles** with realistic data
- **2,000 Research Snippets** with reviews and tags
- **5,000 Intake Logs** over past year
- **10,000 Compound Ratings** from users
- **1,000 Effect Windows** with timing data
- **2,000 Compound Interactions** at targets
- **500 Change Requests** for content moderation

### Metadata & Classifications
- **30+ Action Types** (agonist, antagonist, etc.)
- **40+ Target Types** (GPCR, kinase, etc.)
- **50+ Compound Categories** (psychedelics, nootropics, etc.)
- **Research Tags** with color coding
- **User Roles** and permissions

## 🚀 Quick Start

### Option 1: Full Automated Population (Recommended)
```bash
cd /home/main/Dev/neurobin/core

# Run the complete batch script (30-60 minutes)
./populate_batch.sh
```

### Option 2: Manual Step-by-Step
```bash
cd /home/main/Dev/neurobin/core

# Install additional dependencies
pip install -r populate_requirements.txt

# Run population stages manually
python populate_all_data.py --full --no-limits
```

### Option 3: Selective Population
```bash
# Only basic data types
python populate_all_data.py --targets-only --no-limits

# Only compounds
python populate_all_data.py --compounds-only --no-limits

# Only research/community data
python populate_all_data.py --research-only --no-limits
```

## 📊 Data Sources Used

### Primary APIs
1. **ChEMBL REST API** - Compound and target data
   - URL: https://www.ebi.ac.uk/chembl/api/data/
   - Rate limit: 10 requests/second
   - No authentication required

2. **Reactome Content Service** - Pathway data
   - URL: https://reactome.org/ContentService/
   - Rate limit: 5 requests/second
   - No authentication required

### Secondary APIs (Enhanced Data)
3. **PubChem REST API** - Chemical structures
   - URL: https://pubchem.ncbi.nlm.nih.gov/rest/pug/
   - Rate limit: 5 requests/second

4. **UniProt REST API** - Protein information
   - URL: https://rest.uniprot.org/
   - Rate limit: 10 requests/second

## ⚙️ Configuration Options

### Basic Configuration
Edit `population_config.yaml` to customize:

```yaml
# Limit data amounts
DATA_LIMITS:
  max_compounds_from_chembl: 1000  # Smaller dataset
  max_research_snippets: 100       # Fewer synthetic posts

# API rate limiting
API_SETTINGS:
  chembl_rate_limit: 0.2          # Slower requests
  request_timeout: 60             # Longer timeouts
```

### Advanced Options
```yaml
# Quality filtering
QUALITY_SETTINGS:
  require_smiles_for_compounds: true
  min_mechanism_confidence: 0.5
  filter_by_species: ["Homo sapiens"]

# Performance tuning
DATABASE_SETTINGS:
  batch_size: 500
  use_bulk_create: true
  optimize_queries: true
```

## 🔧 Troubleshooting

### Common Issues

**1. Django Not Found**
```bash
# Ensure you're in the right directory and virtual environment
cd /home/main/Dev/neurobin/core
source ../venv/bin/activate  # if using venv
```

**2. API Rate Limiting**
```bash
# The script handles this automatically, but you can adjust rates:
# Edit population_config.yaml:
API_SETTINGS:
  chembl_rate_limit: 0.5  # Slower requests
```

**3. Memory Issues**
```bash
# For large datasets, use batch processing:
python populate_all_data.py --targets-only --no-limits
python populate_all_data.py --compounds-only --no-limits
# etc.
```

**4. Network Timeouts**
```bash
# Increase timeout in population_config.yaml:
API_SETTINGS:
  request_timeout: 60  # 60 seconds
  max_retries: 5
```

### Recovery Options

**Resume from Checkpoint**
The batch script creates checkpoints. If interrupted, restart:
```bash
./populate_batch.sh  # Will skip completed stages
```

**Clean Start**
```bash
# Remove checkpoints to start fresh
rm .checkpoint_*
./populate_batch.sh
```

## 📈 Performance Expectations

### Time Estimates
- **Basic data types**: 1-2 minutes
- **ChEMBL targets**: 10-15 minutes  
- **ChEMBL compounds**: 15-30 minutes
- **Mechanisms**: 5-10 minutes
- **Reactome pathways**: 10-20 minutes
- **Generated content**: 5-10 minutes
- **Total time**: 45-90 minutes

### Resource Usage
- **CPU**: Moderate (mostly I/O bound)
- **Memory**: 500MB - 2GB peak
- **Disk**: 500MB - 2GB database size
- **Network**: 100-500MB download

### Optimization Tips
1. **Use SSD storage** for faster database writes
2. **Stable internet** for API requests
3. **Close other applications** during population
4. **Use --no-limits** only if you have time and bandwidth

## 🎛️ Customization Guide

### Adding New Data Sources

1. **Create API Client**
```python
class NewAPI(APIClient):
    def __init__(self):
        super().__init__('https://api.example.com/', rate_limit=0.1)
    
    def get_data(self):
        return self.get('endpoint')
```

2. **Add Population Method**
```python
def populate_from_new_api(self):
    data = self.new_api.get_data()
    # Process and save data
```

3. **Update Configuration**
```yaml
DATA_SOURCES:
  new_api:
    enabled: true
    base_url: "https://api.example.com/"
```

### Custom Categories and Types

Edit the script to add your own:
```python
custom_categories = [
    ('My Category', 'Description of my category'),
    # Add more...
]
```

### Filtering Data

Add filters in the population methods:
```python
# Only compounds with molecular weight < 500
if mol_data.get('molecular_weight', 0) > 500:
    continue  # Skip this compound
```

## 📋 Validation and Quality Control

### Automatic Validation
The script includes built-in validation:
- Chemical structure validation (SMILES)
- Molecular weight ranges
- Foreign key constraint checking
- Duplicate detection

### Manual Verification
After population, check data quality:
```bash
# Run Django checks
python manage.py check

# Generate statistics
python manage.py shell -c "
from compounds.models import *
print(f'Compounds: {Compound.objects.count()}')
print(f'Targets: {Target.objects.count()}')
print(f'Interactions: {CompoundTargetInteraction.objects.count()}')
"
```

### Data Export
Export populated data for backup:
```bash
# Export to JSON
python manage.py dumpdata compounds > compounds_backup.json
python manage.py dumpdata research > research_backup.json
```

## 🚀 Next Steps After Population

### 1. Start the Server
```bash
python manage.py runserver 0.0.0.0:8000
```

### 2. Access Admin Interface
- URL: http://localhost:8000/admin/
- Username: `admin`
- Password: `admin123`

### 3. Explore the Data
- Browse compounds: http://localhost:8000/compounds/
- View research: http://localhost:8000/research/
- Check pathway visualizations: http://localhost:8000/compounds/pathway-viewer/

### 4. Create Additional Users
```bash
python manage.py createsuperuser
```

### 5. Customize and Extend
- Add more compound categories
- Import your own research data
- Customize the admin interface
- Add new visualization features

## 🔍 Understanding the Data Structure

### Relationships Map
```
Compound ←→ CompoundTargetInteraction ←→ Target
    ↓                                        ↓
CompoundPathwayEffect ←→ TargetPathwayInteraction
    ↓                           ↓
Research Snippets        Biological Pathways
    ↓
User Reviews & Ratings
```

### Key Models Populated
- `Compound` - Chemical entities with properties
- `Target` - Biological targets (proteins, receptors)
- `CompoundTargetInteraction` - How compounds affect targets
- `TargetPathwayInteraction` - Targets in biological pathways
- `CompoundPathwayEffect` - Compound effects on pathways
- `ResearchSnippet` - Research data and experience reports
- `UserProfile` - User accounts and preferences
- `IntakeLog` - User substance tracking

## 💡 Tips for Production Use

### 1. Database Optimization
```sql
-- Create indexes for frequently queried fields
CREATE INDEX idx_compound_name ON compounds_compound(name);
CREATE INDEX idx_target_type ON compounds_target(target_type);
```

### 2. Caching
Configure Django caching for better performance:
```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

### 3. Backup Strategy
```bash
# Regular database backups
python manage.py dbbackup

# Data export for migration
python manage.py dumpdata --natural-foreign --natural-primary > full_backup.json
```

## 🆘 Support and Contributing

### Getting Help
1. Check the log files: `data_population.log` and `batch_errors.log`
2. Review Django error messages
3. Test API endpoints manually
4. Check network connectivity

### Contributing Improvements
1. Add new data sources
2. Improve data quality validation
3. Add more realistic synthetic data
4. Optimize performance
5. Add new visualization features

## 📜 Legal and Ethical Notes

### Data Usage
- ChEMBL data: CC BY-SA 3.0 license
- Reactome data: CC BY 4.0 license  
- PubChem data: Public domain
- Generated data: Your usage rights

### Rate Limiting Compliance
- All API calls respect published rate limits
- Requests include appropriate User-Agent headers
- Failed requests are retried with exponential backoff
- No excessive burden on free public APIs

### Research Use
This tool is designed for:
- Academic research
- Educational purposes
- Personal knowledge management
- Open science initiatives

Not intended for:
- Commercial drug development without proper licensing
- Medical diagnosis or treatment
- Regulatory submissions
- Any illegal activities

---

**Happy Researching! 🧪🔬**
