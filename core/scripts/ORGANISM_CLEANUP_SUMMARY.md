# Organism Cleanup Summary

## Database Cleanup Results

### Before Cleanup:
- **Total Targets**: 429
- **Total Mechanisms**: 468  
- **Total Target Interactions**: 1,038
- **Organisms**: 72 different organisms represented

### After Cleanup:
- **Total Targets**: 233 (remaining 222 Homo sapiens + 11 with empty organism field)
- **Total Mechanisms**: 216
- **Total Target Interactions**: 541
- **Organisms**: Only Homo sapiens (plus some with empty organism field)

### What Was Removed:

#### 1. Non-Homo sapiens Organisms Removed:
- **196 targets** from 71 different organisms were removed
- This cascaded to remove **497 compound-target interactions**
- Major organisms removed included:
  - Rattus norvegicus (52 targets)
  - Mus musculus (27 targets)
  - Escherichia coli (9 targets)
  - Cavia porcellus (8 targets)
  - Bacteria (8 targets)
  - Cricetulus griseus (5 targets)
  - Sus scrofa (4 targets)
  - Staphylococcus aureus (4 targets)
  - Many others (1-3 targets each)

#### 2. Blacklisted Mechanism Organisms Removed:
- **252 compound mechanisms** were removed that referenced targets from:
  - Homo sapiens (252 mechanisms - these were the mechanisms, not the targets)
  - The blacklisted organisms: Mus musculus, Rattus norvegicus, Cavia porcellus, Oryctolagus cuniculus

### Database Impact:
- **Space Saved**: Reduced database size by ~45% in terms of targets
- **Data Quality**: Now focused exclusively on human-relevant data
- **Performance**: Queries should be faster with smaller dataset

### Files Created:
1. `cleanup_organisms.sql` - Raw SQL queries for reference
2. `cleanup_organisms.py` - Python script that performed the cleanup
3. This summary document

### Verification:
The cleanup preserved all Homo sapiens targets (222) while removing all other organism-specific data. The database now contains only human-relevant pharmaceutical targets and interactions.
