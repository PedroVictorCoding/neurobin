# ChemBio Importer Usage Guide

## Quick Start

### 1. Initialize Database

```bash
python -m chembio_importer --init-db
```

### 2. Import Sample Data

```bash
# Import 100 compounds from ChEMBL with rate limiting
python -m chembio_importer --from-chembl --limit 100 --slow

# Import pathways for the imported compounds
python -m chembio_importer --from-reactome --slow
```

### 3. Check Results

```bash
python -m chembio_importer --stats
```

## Command Line Interface

### Basic Commands

```bash
# Show help
python -m chembio_importer --help

# Initialize database tables
python -m chembio_importer --init-db

# Import from ChEMBL
python -m chembio_importer --from-chembl --slow

# Import from Reactome
python -m chembio_importer --from-reactome --slow

# Import specific compound
python -m chembio_importer --compound CHEMBL25 --slow

# Limit import size (for testing)
python -m chembio_importer --from-chembl --limit 1000 --slow

# Show database statistics
python -m chembio_importer --stats

# Export data
python -m chembio_importer --export ./exports
```

### Command Options

| Option | Description |
|--------|-------------|
| `--from-chembl` | Import compounds from ChEMBL |
| `--from-reactome` | Import pathways from Reactome |
| `--compound CHEMBL_ID` | Import specific compound |
| `--limit N` | Limit import to N compounds |
| `--slow` | Enable rate limiting (recommended) |
| `--init-db` | Initialize database tables |
| `--stats` | Show database statistics |
| `--export DIR` | Export data to directory |
| `--log-level LEVEL` | Set logging level (DEBUG, INFO, WARNING, ERROR) |

## Python API Usage

### Basic Import Workflow

```python
from chembio_importer.__main__ import ChemBioImporter

# Create importer instance
importer = ChemBioImporter()

# Initialize database
importer.initialize_database()

# Import from ChEMBL (limit for demo)
importer.import_from_chembl(limit=100)

# Import pathways for imported targets
importer.import_pathways_from_reactome(targets_only=True)

# Get statistics
stats = importer.get_statistics()
print(f"Imported {stats['database_stats']['compounds']} compounds")
```

### Working with Individual Clients

```python
from chembio_importer.parsers import chembl_client, reactome_client

# Get compound data
compound = chembl_client.get_compound_by_id("CHEMBL25")
print(f"Compound: {compound['name']}")

# Get compound targets
targets = chembl_client.get_compound_targets("CHEMBL25")
print(f"Found {len(targets)} targets")

# Get pathways for a protein
pathways = reactome_client.get_pathways_for_identifier("P04637")  # TP53
print(f"Found {len(pathways)} pathways")
```

### Database Queries

```python
from chembio_importer import db_manager
from chembio_importer.models import Compound, Target, Pathway

with db_manager.get_session() as session:
    # Find compounds by name
    compounds = session.query(Compound).filter(
        Compound.name.like('%morphine%')
    ).all()
    
    # Find high-affinity interactions
    from chembio_importer.models import CompoundTargetInteraction
    
    interactions = session.query(CompoundTargetInteraction).filter(
        CompoundTargetInteraction.activity_value < 100,  # < 100 nM
        CompoundTargetInteraction.activity_units == 'nM'
    ).all()
    
    # Find pathways by species
    human_pathways = session.query(Pathway).filter(
        Pathway.species == 'Homo sapiens'
    ).all()
```

## Common Use Cases

### 1. Import Specific Therapeutic Area

```python
# Example: Import antidepressants
antidepressant_chembl_ids = [
    "CHEMBL637",   # Fluoxetine
    "CHEMBL1213", # Sertraline  
    "CHEMBL1229562", # Paroxetine
    "CHEMBL1229317", # Citalopram
]

importer = ChemBioImporter()
importer.initialize_database()

for chembl_id in antidepressant_chembl_ids:
    importer.import_from_chembl(specific_compound=chembl_id)

importer.import_pathways_from_reactome(targets_only=True)
```

### 2. Analyze Compound Properties

```python
with db_manager.get_session() as session:
    # Find drug-like compounds (Lipinski's Rule of Five)
    drug_like = session.query(Compound).filter(
        Compound.molecular_weight <= 500,
        Compound.logp <= 5,
        Compound.hbd <= 5,
        Compound.hba <= 10
    ).all()
    
    print(f"Found {len(drug_like)} drug-like compounds")
```

### 3. Find Multi-Target Compounds

```python
with db_manager.get_session() as session:
    # Find compounds with many targets
    from sqlalchemy import func
    
    multi_target_compounds = session.query(
        Compound.chembl_id,
        Compound.name,
        func.count(CompoundTargetInteraction.id).label('target_count')
    ).join(CompoundTargetInteraction).group_by(
        Compound.id
    ).having(
        func.count(CompoundTargetInteraction.id) > 5
    ).all()
    
    for chembl_id, name, count in multi_target_compounds:
        print(f"{name} ({chembl_id}): {count} targets")
```

### 4. Pathway Analysis

```python
with db_manager.get_session() as session:
    # Find most common pathways
    from collections import Counter
    
    pathway_counts = Counter()
    compounds = session.query(Compound).all()
    
    for compound in compounds:
        for pathway in compound.pathways:
            pathway_counts[pathway.name] += 1
    
    print("Most common pathways:")
    for pathway, count in pathway_counts.most_common(10):
        print(f"  {pathway}: {count} compounds")
```

## Configuration and Optimization

### Rate Limiting Configuration

```python
# In config.py or environment variables
SLOW_MODE = True          # Enable rate limiting
SLEEP_INTERVAL = 2        # Wait 2 seconds between requests  
MAX_RETRIES = 3          # Retry failed requests 3 times
RETRY_DELAY = 5          # Wait 5 seconds before retry
```

### Database Optimization

```python
# Use PostgreSQL for large datasets
DATABASE_URL = "postgresql://user:password@localhost:5432/chembio_db"

# Batch processing settings
CHEMBL_BATCH_SIZE = 100   # Increase for faster imports (but respect API limits)
```

### Memory Management

```python
# Process large datasets in chunks
def import_large_dataset():
    importer = ChemBioImporter()
    
    # Import in smaller batches
    batch_size = 1000
    for i in range(0, 10000, batch_size):
        importer.import_from_chembl(
            limit=batch_size,
            offset=i  # Note: you'd need to implement offset support
        )
        
        # Clear memory periodically
        import gc
        gc.collect()
```

## Monitoring and Logging

### Enable Detailed Logging

```bash
# Set log level
export LOG_LEVEL=DEBUG

# Run with verbose logging
python -m chembio_importer --from-chembl --limit 10 --log-level DEBUG
```

### Monitor Progress

```python
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# The importer will log progress automatically
importer = ChemBioImporter()
importer.import_from_chembl(limit=1000)  # Progress will be logged
```

### Check Import Status

```python
with db_manager.get_session() as session:
    # Check import logs
    from chembio_importer.models import ImportLog
    
    recent_imports = session.query(ImportLog).order_by(
        ImportLog.started_at.desc()
    ).limit(10).all()
    
    for log in recent_imports:
        print(f"{log.operation_type}: {log.status} "
              f"({log.records_processed} records)")
```

## Troubleshooting

### Common Issues

1. **API Rate Limiting**
   - Always use `--slow` flag
   - Increase `SLEEP_INTERVAL` if getting 429 errors

2. **Memory Issues**
   - Use PostgreSQL instead of SQLite
   - Import in smaller batches
   - Monitor memory usage during large imports

3. **Network Timeouts**
   - Check internet connection
   - Increase timeout values in config
   - Use retry logic

4. **Database Locks**
   - Ensure only one import process runs at a time
   - Use proper database connection pooling

### Error Recovery

```python
# Resume interrupted import
try:
    importer.import_from_chembl(limit=10000)
except Exception as e:
    print(f"Import failed: {e}")
    
    # Get current status
    stats = importer.get_statistics()
    print(f"Processed {stats['import_stats']['compounds_processed']} compounds")
    
    # Resume from where we left off (you'd need to implement resume logic)
```

## Best Practices

1. **Always use rate limiting** (`--slow`) for production imports
2. **Start with small limits** to test your setup
3. **Monitor disk space** during large imports  
4. **Use PostgreSQL** for production databases
5. **Backup your database** before major imports
6. **Check API status** if experiencing issues
7. **Log import operations** for debugging

## Performance Benchmarks

Typical performance (with `--slow` enabled):

- **ChEMBL compounds**: ~30 compounds/minute
- **Reactome pathways**: ~50 pathways/minute  
- **Database size**: ~100MB per 10,000 compounds

For production imports without rate limiting:
- **ChEMBL compounds**: ~200-500 compounds/minute
- **Risk**: API may ban your IP address
