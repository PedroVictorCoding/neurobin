# Compound Mechanisms Update Script

This script updates compound mechanisms of action by fetching comprehensive data from ChEMBL's Drug Mechanisms API.

## Overview

The `update_compound_mechanisms` management command goes through each compound in your database and:

1. **Fetches mechanisms** from ChEMBL Drug Mechanisms API for each compound
2. **Creates missing targets** with proper ChEMBL IDs and types
3. **Maps action types** from ChEMBL to your database schema
4. **Creates mechanism records** linking compounds to targets with interaction types
5. **Handles duplicates** and provides comprehensive logging

## Usage Examples

### Basic Usage

Update all compounds without existing mechanisms:
```bash
python manage.py update_compound_mechanisms
```

### Specific Compound

Update mechanisms for a single compound:
```bash
python manage.py update_compound_mechanisms --compound-id CHEMBL25
```

### Testing & Development

Test with a small sample (dry run):
```bash
python manage.py update_compound_mechanisms --dry-run --max-compounds 5
```

### Production Updates

Replace existing mechanisms with fresh ChEMBL data:
```bash
python manage.py update_compound_mechanisms --replace-existing --batch-size 30 --delay 0.3
```

Resume from a specific point (if interrupted):
```bash
python manage.py update_compound_mechanisms --start-from 1000 --max-compounds 500
```

### Performance Tuning

For slower connections or rate limiting:
```bash
python manage.py update_compound_mechanisms --batch-size 10 --delay 0.5
```

For faster processing:
```bash
python manage.py update_compound_mechanisms --batch-size 100 --delay 0.1
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--compound-id` | Update specific compound by ChEMBL ID | All compounds |
| `--batch-size` | Number of compounds per batch | 50 |
| `--delay` | Delay between API calls (seconds) | 0.2 |
| `--replace-existing` | Replace existing mechanisms | Skip existing |
| `--dry-run` | Show what would be updated | Actually update |
| `--max-compounds` | Limit for testing | No limit |
| `--start-from` | Start from compound index | 0 |

## What Gets Updated

### Mechanism Data
- **Target Information**: ChEMBL target ID, name, type
- **Action Type**: Agonist, antagonist, inhibitor, etc.
- **Interaction Type**: How the compound interacts with the target
- **Description**: Mechanism description from ChEMBL

### Automatic Mappings
- **Action Types**: ChEMBL → Your schema (e.g., "blocker" → "antagonist")
- **Target Types**: ChEMBL → Your schema (e.g., "single protein" → "protein")
- **Data Cleanup**: Filters empty targets, normalizes names

### Database Objects Created
- `CompoundMechanismOfAction` records
- `Target` records (if missing)
- Proper linking between compounds and mechanisms

## API Data Source

The script uses ChEMBL's Drug Mechanisms endpoint:
```
https://www.ebi.ac.uk/chembl/api/data/mechanism
```

### Sample ChEMBL Response
```json
{
  "mechanisms": [
    {
      "molecule_chembl_id": "CHEMBL25",
      "target_chembl_id": "CHEMBL1863", 
      "target_pref_name": "Cyclooxygenase-1",
      "target_type": "SINGLE PROTEIN",
      "action_type": "INHIBITOR",
      "mechanism_of_action": "Cyclooxygenase inhibitor"
    }
  ]
}
```

## Performance Notes

- **Rate Limiting**: Default 0.2s delay prevents API overload
- **Batch Processing**: Processes compounds in configurable batches  
- **Error Handling**: Continues on errors, logs issues
- **Memory Efficient**: Uses Django QuerySet iteration
- **Resumable**: Can restart from any point using `--start-from`

## Monitoring Progress

The script provides real-time feedback:
```
🔬 Starting compound mechanisms update from ChEMBL...
📊 Found 52790 compounds to process
🔄 Processing batch 1 (50 compounds)...
  [1/52790] ASPIRIN (CHEMBL25)
    🔍 Found 1 mechanisms
    ➕ Created: Cyclooxygenase-1 - inhibitor
    ✅ Added 1 mechanisms
```

## Error Handling

- **API Failures**: Logged and skipped, processing continues
- **Invalid Data**: Filtered out (empty targets, malformed responses)
- **Database Errors**: Transactions ensure data consistency
- **Network Issues**: Automatic retries and timeouts

## Output Statistics

Final summary shows:
- Compounds processed vs skipped
- Mechanisms created vs updated  
- New targets created
- Error count with log references

## Best Practices

1. **Start Small**: Test with `--dry-run` and `--max-compounds` first
2. **Monitor Logs**: Check Django logs for detailed error information
3. **Use Delays**: Respect ChEMBL API rate limits (0.2-0.5s delays)
4. **Backup First**: Always backup your database before large updates
5. **Resume Capability**: Use `--start-from` for interrupted runs

## Troubleshooting

### Common Issues

**No mechanisms found**: Some compounds may not have mechanism data in ChEMBL
**API rate limiting**: Increase `--delay` if you get 429 errors
**Memory usage**: Reduce `--batch-size` for large datasets
**Network timeouts**: Check internet connection and ChEMBL API status

### Debug Mode
```bash
python manage.py update_compound_mechanisms --verbosity 2 --max-compounds 1
```

This comprehensive script ensures your compound mechanisms are always up-to-date with the latest ChEMBL data!
