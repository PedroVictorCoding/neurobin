# Compound Import Guide - Filtering Empty and CHEMBL Names

This guide shows how to import compounds from ChEMBL while filtering out:
1. Compounds with empty names
2. Compounds whose names only contain "CHEMBL" identifiers

## Quick Start

### Import Filtered Compounds (Recommended)

Use the dedicated filtered import command:

```bash
# Import 1000 approved drugs with filtering
python manage.py import_filtered_compounds --max-compounds 1000 --source approved

# Import bioactive compounds (with known activity)
python manage.py import_filtered_compounds --max-compounds 500 --source bioactive

# Import compounds with known mechanisms
python manage.py import_filtered_compounds --max-compounds 300 --source mechanisms

# Dry run to see what would be imported without saving
python manage.py import_filtered_compounds --max-compounds 50 --source approved --dry-run
```

### Use the Full Population Pipeline

The main population script has been updated with filtering:

```bash
# Import only compounds (with filtering applied automatically)
python manage.py populate_all_data --compounds-only --max-compounds 1000

# Full pipeline (compounds + interactions)
python manage.py populate_all_data --max-compounds 500
```

## Command Options

### import_filtered_compounds

- `--max-compounds`: Maximum number of compounds to process (default: 1000)
- `--batch-size`: API batch size (default: 100)
- `--delay`: Delay between API calls in seconds (default: 0.1)
- `--source`: Source of compounds
  - `approved`: FDA/EMA approved drugs (highest quality)
  - `bioactive`: Compounds with known biological activity
  - `mechanisms`: Compounds with known mechanisms of action
- `--dry-run`: Show what would be imported without saving to database

### populate_all_data

- `--compounds-only`: Only import compounds
- `--interactions-only`: Only import interactions for existing compounds
- `--max-compounds`: Maximum compounds to process
- `--batch-size`: API batch size (default: 100)
- `--delay`: Delay between API calls (default: 0.1)

## Filtering Logic

The filtering removes compounds where:

1. **Empty Names**: After processing, the compound has no valid name
2. **CHEMBL Names Only**: The only available names contain "CHEMBL" (e.g., "CHEMBL123456")

### What Gets Kept:
- ✅ "ASPIRIN" (proper drug name)
- ✅ "IBUPROFEN" (proper drug name)
- ✅ "ACETAMINOPHEN" (proper drug name)

### What Gets Filtered Out:
- ❌ "" (empty name)
- ❌ "CHEMBL123456" (only CHEMBL ID)
- ❌ "   " (whitespace only)

## Recommended Workflow

1. **Start with approved drugs** (highest quality):
   ```bash
   python manage.py import_filtered_compounds --max-compounds 2000 --source approved
   ```

2. **Add bioactive compounds** for broader coverage:
   ```bash
   python manage.py import_filtered_compounds --max-compounds 1000 --source bioactive
   ```

3. **Import interactions** for the compounds:
   ```bash
   python manage.py populate_all_data --interactions-only
   ```

4. **Check results**:
   ```bash
   python manage.py shell -c "from compounds.models import Compound; print(f'Total compounds: {Compound.objects.count()}')"
   ```

## Statistics and Monitoring

The import commands provide detailed statistics:
- Compounds fetched from API
- Compounds filtered out (empty names)
- Compounds filtered out (CHEMBL names only)
- Successfully imported compounds
- Updated existing compounds
- API errors

## Performance Tips

- Use `--batch-size 50` for slower networks
- Increase `--delay 0.2` if you get rate limiting errors
- Start with small `--max-compounds` for testing
- Use `--dry-run` to preview results before importing

## Example Output

```
🧬 IMPORTING FILTERED COMPOUNDS
==================================================
Source: approved
Max compounds: 100

Processing batch 1 (100 compounds)...
  IMPORTED: PRAZOSIN (CHEMBL2)
  IMPORTED: NICOTINE (CHEMBL3)
  FILTERED: CHEMBL999 - only CHEMBL names available
  IMPORTED: OFLOXACIN (CHEMBL4)
  ...

📊 IMPORT STATISTICS
==================================================
Compounds fetched: 100
Filtered out (empty names): 5
Filtered out (CHEMBL names): 12
Successfully imported: 83
Updated existing: 0
Errors: 0

Filter rate: 17.0% compounds excluded
✅ Import completed!
```

This filtering ensures you get a clean, named compound database suitable for drug discovery and research applications.
