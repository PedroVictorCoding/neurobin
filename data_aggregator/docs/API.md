# ChemBio Importer API Reference

## Overview

The ChemBio Importer provides a comprehensive API for importing and cross-referencing compound data from ChEMBL and Reactome databases.

## Main Classes

### ChemBioImporter

The main importer class that coordinates data import from multiple sources.

```python
from chembio_importer.__main__ import ChemBioImporter

importer = ChemBioImporter()
```

#### Methods

- `initialize_database()` - Initialize database tables
- `import_from_chembl(limit=None, specific_compound=None)` - Import compounds from ChEMBL
- `import_pathways_from_reactome(targets_only=True)` - Import pathways from Reactome
- `get_statistics()` - Get database and import statistics

### Database Manager

Handles database operations and connections.

```python
from chembio_importer import db_manager

with db_manager.get_session() as session:
    # Database operations
    pass
```

#### Methods

- `create_tables()` - Create database schema
- `get_session()` - Context manager for database sessions
- `get_or_create_compound(session, chembl_id, **kwargs)` - Get or create compound
- `get_or_create_target(session, chembl_id, **kwargs)` - Get or create target
- `get_or_create_pathway(session, stable_id, **kwargs)` - Get or create pathway

### ChEMBL Client

Client for ChEMBL API interactions.

```python
from chembio_importer.parsers import chembl_client

compound = chembl_client.get_compound_by_id("CHEMBL25")
```

#### Methods

- `get_compound_by_id(chembl_id)` - Get compound details
- `get_compound_targets(chembl_id)` - Get compound target interactions
- `get_compound_mechanisms(chembl_id)` - Get mechanism of action data
- `get_target_by_id(target_chembl_id)` - Get target details
- `get_all_compounds(limit=None)` - Iterator for all compounds

### Reactome Client

Client for Reactome API interactions.

```python
from chembio_importer.parsers import reactome_client

pathways = reactome_client.get_pathways_for_identifier("P04637")
```

#### Methods

- `get_pathways_for_identifier(identifier, identifier_type='uniprot')` - Get pathways for protein
- `get_pathway_participants(stable_id)` - Get participating proteins in pathway
- `search_pathways(query, species='Homo sapiens')` - Search pathways
- `map_targets_to_pathways(target_identifiers)` - Map multiple targets to pathways

### UniProt Client

Client for UniProt API interactions (optional enhancement).

```python
from chembio_importer.parsers import uniprot_client

protein = uniprot_client.get_protein_by_uniprot_id("P04637")
```

#### Methods

- `get_protein_by_uniprot_id(uniprot_id)` - Get protein details
- `search_proteins(query, organism='human')` - Search proteins
- `enrich_target_data(target_data)` - Enrich target with UniProt data

## Database Models

### Compound

Represents a chemical compound from ChEMBL.

**Fields:**
- `chembl_id` - ChEMBL identifier
- `name` - Compound name
- `canonical_smiles` - SMILES structure
- `inchi` - InChI identifier
- `molecular_weight` - Molecular weight in Da
- `logp` - LogP value
- `approval_status` - Regulatory approval status
- `effect_profile` - JSON field with effect predictions

### Target

Represents a biological target (protein, enzyme, receptor).

**Fields:**
- `chembl_id` - ChEMBL target identifier
- `name` - Target name
- `gene_symbol` - Gene symbol
- `organism` - Species
- `target_type` - Type (enzyme, receptor, etc.)
- `uniprot_id` - UniProt identifier

### Pathway

Represents a biological pathway from Reactome.

**Fields:**
- `stable_id` - Reactome stable identifier
- `name` - Pathway name
- `description` - Pathway description
- `species` - Species
- `reactome_url` - Link to Reactome

### CompoundTargetInteraction

Represents compound-target interactions with mechanism and affinity data.

**Fields:**
- `mechanism` - Mechanism of action
- `activity_type` - Type of activity (IC50, Ki, etc.)
- `activity_value` - Numeric activity value
- `activity_units` - Units (normalized to nM)
- `confidence_score` - Data confidence

## Configuration

The package uses environment variables and `config.py` for configuration:

```python
# API rate limiting
SLOW_MODE = True
SLEEP_INTERVAL = 2  # seconds

# Database
DATABASE_URL = "sqlite:///chem_react.db"

# Batch sizes
CHEMBL_BATCH_SIZE = 50
```

## Error Handling

The package includes comprehensive error handling:

- API rate limiting with automatic retry
- Database transaction management
- Data validation and cleaning
- Graceful degradation on partial failures

## Performance Considerations

- Use `SLOW_MODE=True` for production to respect API limits
- Batch processing for large imports
- Database connection pooling
- Efficient querying with indexes

## Example Usage

```python
from chembio_importer.__main__ import ChemBioImporter

# Initialize
importer = ChemBioImporter()
importer.initialize_database()

# Import specific compound
importer.import_from_chembl(specific_compound="CHEMBL25")

# Import pathways for existing targets
importer.import_pathways_from_reactome(targets_only=True)

# Get statistics
stats = importer.get_statistics()
print(f"Imported {stats['database_stats']['compounds']} compounds")
```
