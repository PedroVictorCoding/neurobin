# ChEMBL Compound Interaction Import System

## 🧠 Overview

This system provides automated import of compound-target interaction data from ChEMBL's official API into the Neurobin platform. It populates the `Compound`, `Target`, `CompoundTargetInteraction`, and `CompoundToCompoundTargetInteraction` models with real pharmaceutical data.

The system supports both **ChEMBL ID-based imports** and **name-based compound searches**.

## 🔌 ChEMBL API Integration

### Supported Endpoints

- **Mechanisms**: `https://www.ebi.ac.uk/chembl/api/data/mechanism.json`
- **Targets**: `https://www.ebi.ac.uk/chembl/api/data/target/{target_id}.json`
- **Activities**: `https://www.ebi.ac.uk/chembl/api/data/activity.json`
- **Molecule Search**: `https://www.ebi.ac.uk/chembl/api/data/molecule.json` (for name-based search)

### Data Mapping

| ChEMBL Field | Neurobin Model | Field | Notes |
|--------------|----------------|-------|-------|
| `molecule_chembl_id` | `Compound` | `chembl_id` | Primary identifier |
| `target_chembl_id` | `Target` | `chembl_id` | Target identifier |
| `pref_name` | `Target` | `name` | Preferred target name |
| `target_type` | `Target` | `target_type` | Normalized type |
| `mechanism_of_action` | `CompoundTargetInteraction` | `mechanism` | Normalized mechanism |
| `standard_value` | `CompoundTargetInteraction` | `affinity_level` | Calculated affinity |

## 🚀 Installation & Setup

### 1. Install Requirements

```bash
# Install ChEMBL import dependencies
pip install requests urllib3

# Or install from requirements.txt
pip install -r requirements.txt
```

### 2. Run Database Migration

```bash
# Generate migration for new ChEMBL fields
python manage.py makemigrations compounds

# Apply migration
python manage.py migrate
```

### 3. Create Sample Compounds

```bash
# Run test script to create sample data
python test_chembl_import.py
```

## 📊 Model Updates

### Updated Models

#### `Compound` Model
- **New Field**: `chembl_id` - ChEMBL compound identifier
- **Enhanced**: Search functionality includes ChEMBL ID

#### `Target` Model  
- **New Field**: `chembl_id` - ChEMBL target identifier
- **New Field**: `target_type` - Normalized target type
- **New Field**: `organism` - Target organism (e.g., "Homo sapiens")

#### `CompoundTargetInteraction` Model
- **Enhanced**: Additional mechanism choices (modulator, blocker, opener)
- **New Field**: `source` - Data source tracking
- **Updated**: Affinity level choices aligned with ChEMBL data

#### `CompoundToCompoundTargetInteraction` Model
- **Updated**: Field names changed for consistency (`compound1`/`compound2`)
- **Updated**: `shared_target` field for clarity
- **Enhanced**: Better interaction type inference

## 🛠️ Usage

### Basic Import Commands

```bash
# Import specific compounds by ChEMBL ID
python manage.py import_chembl_interactions --compounds=CHEMBL25,CHEMBL154,CHEMBL1487

# Import all compounds with ChEMBL IDs
python manage.py import_chembl_interactions --all-compounds

# Import from file
echo "CHEMBL25\nCHEMBL154\nCHEMBL1487" > compounds.txt
python manage.py import_chembl_interactions --file=compounds.txt

# Search by compound names (NEW!)
python manage.py import_chembl_interactions --search-names="caffeine,aspirin,modafinil"

# Search single compound by name
python manage.py import_chembl_interactions --search-names="ligandrol"

# Control batch size and compound interactions
python manage.py import_chembl_interactions --compounds=CHEMBL25,CHEMBL154 --batch-size=5

# Enable slow mode to prevent API blocking
python manage.py import_chembl_interactions --compounds=CHEMBL25,CHEMBL154 --slow-mode

# Combine name search with slow mode
python manage.py import_chembl_interactions --search-names="caffeine,aspirin" --slow-mode
```

### Advanced Options

```bash
# Skip compound-to-compound interaction creation
python manage.py import_chembl_interactions --compounds=CHEMBL25 --create-compound-interactions=false

# Larger batch size for faster processing
python manage.py import_chembl_interactions --all-compounds --batch-size=20

# Enable slow mode to prevent API rate limiting/blocking
python manage.py import_chembl_interactions --all-compounds --slow-mode

# Combine slow mode with smaller batches for maximum politeness
python manage.py import_chembl_interactions --all-compounds --slow-mode --batch-size=5
```

## 🧪 Sample Compound ChEMBL IDs

### Nootropics & Cognitive Enhancers
```python
nootropic_compounds = [
    "CHEMBL25",     # Caffeine
    "CHEMBL1487",   # Modafinil
    "CHEMBL2103745", # TAK-653 (AMPA modulator)
    "CHEMBL154",    # Fluoxetine (cognitive effects)
]
```

### Psychedelics & Research Compounds
```python
psychedelic_compounds = [
    "CHEMBL112",    # LSD
    "CHEMBL2153138", # Psilocybin
    "CHEMBL122",    # Ketamine
    "CHEMBL1750",   # DMT
]
```

### Classic Pharmaceuticals
```python
pharma_compounds = [
    "CHEMBL134",    # Diazepam
    "CHEMBL17",     # Morphine
    "CHEMBL113",    # Amphetamine
    "CHEMBL240",    # Methylphenidate
]
```

## � Name-Based Search Feature

### How It Works

The system can search ChEMBL by compound names and automatically convert them to ChEMBL IDs for import. This uses multiple search strategies:

1. **Exact Synonym Match**: Searches molecule synonyms for exact matches
2. **Preferred Name Match**: Searches the preferred compound name field  
3. **Fuzzy Search**: Searches synonyms with partial matching

### Search Examples

```bash
# Single compound search
python manage.py import_chembl_interactions --search-names="caffeine"
# Output: caffeine → CHEMBL113

# Multiple compounds
python manage.py import_chembl_interactions --search-names="caffeine,aspirin,modafinil"
# Output: 
#   caffeine → CHEMBL113
#   aspirin → CHEMBL25  
#   modafinil → CHEMBL1373

# With slow mode for API politeness
python manage.py import_chembl_interactions --search-names="ligandrol,ostarine" --slow-mode
```

### Search Success Tips

- Use common/generic names (e.g., "caffeine" not "1,3,7-trimethylxanthine")
- Try alternative spellings if not found
- Use drug brand names (e.g., "prozac" for fluoxetine)
- IUPAC names often work well

## �🔄 Import Process Flow

### 1. Compound Processing
```
For each ChEMBL ID:
├── Find compound in database (by ChEMBL ID or name)
├── Fetch mechanism data from ChEMBL API
├── Fetch activity data for affinity calculation
└── Process each mechanism → create interactions
```

### 2. Target Creation
```
For each target in mechanisms:
├── Check if target exists (by ChEMBL ID)
├── Fetch target details from ChEMBL API
├── Create Target record with:
│   ├── Name (preferred name)
│   ├── Type (normalized)
│   ├── Description
│   └── Organism
```

### 3. Interaction Creation
```
For each compound-target pair:
├── Normalize mechanism terms
├── Calculate affinity level from activities
├── Create/update CompoundTargetInteraction
└── Set source = "ChEMBL"
```

### 4. Compound-Compound Analysis
```
For each target with multiple compounds:
├── Find all compound pairs sharing the target
├── Analyze mechanisms for interaction type:
│   ├── Both agonists → synergistic
│   ├── Agonist + antagonist → antagonistic  
│   ├── Substrate + inhibitor → enzyme_inhibition
│   └── Different mechanisms → competitive
└── Create CompoundToCompoundTargetInteraction
```

## 🎯 Mechanism Normalization

### ChEMBL → Neurobin Mapping

| ChEMBL Mechanism | Normalized | Notes |
|------------------|------------|-------|
| `agonist`, `partial agonist`, `full agonist` | `agonist` | Receptor activation |
| `antagonist`, `competitive antagonist` | `antagonist` | Receptor blockade |
| `inhibitor`, `competitive inhibitor` | `inhibitor` | Enzyme/protein inhibition |
| `positive modulator`, `negative modulator` | `modulator` | Allosteric modulation |
| `channel blocker`, `blocker` | `blocker` | Ion channel blockade |
| `substrate` | `substrate` | Enzyme substrate |
| `inducer` | `inducer` | Enzyme induction |

### Affinity Level Calculation

```python
# Based on IC50/EC50/Ki/Kd values
if value < 100 nM:     return 'high'
elif value < 1000 nM:  return 'medium'  
else:                  return 'low'
```

## 📈 Performance & Rate Limiting

### API Rate Limiting & Slow Mode
- **Normal Mode**: Default 10 compounds per batch, 2 seconds between batches
- **Slow Mode** (`--slow-mode`): Extended delays to prevent API blocking:
  - 10 seconds between batches
  - 3 seconds before each compound's API calls
  - 2 seconds between mechanism and activity API calls
  - 1 second between mechanism processing
  - 2 seconds before target creation API calls
  - Longer retry delays (exponential backoff × 3)
- **Retry Logic**: 3 attempts with exponential backoff
- **Timeout**: 30 seconds per request

### When to Use Slow Mode
- **Large datasets**: When importing many compounds (>50)
- **API restrictions**: If you're hitting rate limits
- **Shared IP**: When multiple users might be accessing ChEMBL
- **Background processing**: For automated/unattended imports
- **Politeness**: To be respectful to ChEMBL's free API service

### Database Optimization
```python
# Efficient querying with select_related
interactions = CompoundTargetInteraction.objects.select_related(
    'compound', 'target'
).filter(source='ChEMBL')

# Bulk operations for large datasets
CompoundTargetInteraction.objects.bulk_create(
    interactions, ignore_conflicts=True
)
```

## 🔍 Monitoring & Logging

### Import Progress Tracking
```
[i] Slow mode enabled - using extended delays to prevent API blocking
[→] Processing CHEMBL25...
[✓] Created interaction: Caffeine → Adenosine A2A receptor (antagonist)
[→] Created target: Adenosine A2A receptor (receptor)
[✓] Created 3 interactions for Caffeine
[i] Processed 1/5, sleeping 10s...
[→] Processing CHEMBL154...
[✓] Fluoxetine ↔ Caffeine → competitive
```

### Error Handling
```
[!] No mechanisms found for CHEMBL999
[✗] Error processing CHEMBL123: Connection timeout
[!] Compound CHEMBL456 not found in database, skipping
```

## 🛡️ Data Quality & Validation

### Duplicate Prevention
- **Unique Constraints**: Compound + Target + Mechanism
- **Consistent Ordering**: compound1.id < compound2.id
- **Source Tracking**: Prevents overwriting manual data

### Data Validation
```python
# Mechanism validation
VALID_MECHANISMS = [
    'agonist', 'antagonist', 'inhibitor', 
    'modulator', 'substrate', 'blocker'
]

# Affinity validation  
VALID_AFFINITIES = ['high', 'medium', 'low', 'unknown']
```

## 🔧 Troubleshooting

### Common Issues

#### 1. Import Command Not Found
```bash
# Ensure you're in the correct directory
cd /path/to/neurobin/core
python manage.py import_chembl_interactions --help
```

#### 2. Requests Library Missing
```bash
pip install requests
# Or
pip install -r requirements.txt
```

#### 3. Database Migration Issues
```bash
# Reset migrations if needed
python manage.py migrate compounds zero
python manage.py migrate compounds
```

#### 4. API Rate Limiting
```bash
# Use slow mode for large imports
python manage.py import_chembl_interactions --all-compounds --slow-mode

# Reduce batch size
python manage.py import_chembl_interactions --batch-size=5
```

#### 5. No Compounds Found
```bash
# Create test compounds first
python test_chembl_import.py
```

## 📚 Extension Ideas

### Custom Import Sources
```python
# Add support for other databases
class PubChemImporter(ChEMBLImporter):
    BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/"
    
class DrugBankImporter(ChEMBLImporter):
    BASE_URL = "https://go.drugbank.com/structures/"
```

### Advanced Analytics
```python
# Interaction network analysis
def analyze_interaction_networks():
    # Find highly connected compounds
    # Identify interaction clusters
    # Calculate network metrics
```

### Automated Updates
```python
# Celery task for periodic updates
@shared_task
def update_chembl_data():
    # Check for new ChEMBL releases
    # Update existing interactions
    # Import new compounds
```

---

**Last Updated**: July 2025  
**Version**: 1.0  
**ChEMBL API Version**: 31
