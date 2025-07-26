# SQL Commands to Remove Compounds with CHEMBL Names

## For SQLite (your current database):

### 1. Check what will be deleted (count):
```sql
SELECT COUNT(*) as compounds_to_delete 
FROM compounds_compound 
WHERE name LIKE '%CHEMBL%';
```

### 2. Preview compounds to be deleted:
```sql
SELECT id, name, chembl_id 
FROM compounds_compound 
WHERE name LIKE '%CHEMBL%' 
LIMIT 10;
```

### 3. Delete compounds containing CHEMBL (BE CAREFUL!):
```sql
DELETE FROM compounds_compound 
WHERE name LIKE '%CHEMBL%';
```

### 4. Case-insensitive version (recommended):
```sql
DELETE FROM compounds_compound 
WHERE UPPER(name) LIKE '%CHEMBL%';
```

## For PostgreSQL (if you switch databases):
```sql
-- Case-insensitive delete
DELETE FROM compounds_compound 
WHERE name ILIKE '%CHEMBL%';
```

## For MySQL:
```sql
-- Case-insensitive delete
DELETE FROM compounds_compound 
WHERE name LIKE '%CHEMBL%';
```

## Safety Commands:

### Before deletion - create backup:
```bash
# For SQLite
cp db.sqlite3 db_backup_before_chembl_cleanup.sqlite3
```

### Verify deletion worked:
```sql
SELECT COUNT(*) as remaining_chembl_compounds 
FROM compounds_compound 
WHERE UPPER(name) LIKE '%CHEMBL%';
```

### Check remaining compounds:
```sql
SELECT COUNT(*) as total_remaining_compounds 
FROM compounds_compound;
```

## Transaction-Safe Version (Recommended):
```sql
BEGIN TRANSACTION;

-- Show what will be deleted
SELECT COUNT(*) as will_delete FROM compounds_compound WHERE UPPER(name) LIKE '%CHEMBL%';

-- Perform the deletion
DELETE FROM compounds_compound WHERE UPPER(name) LIKE '%CHEMBL%';

-- Check results
SELECT COUNT(*) as remaining_total FROM compounds_compound;
SELECT COUNT(*) as remaining_chembl FROM compounds_compound WHERE UPPER(name) LIKE '%CHEMBL%';

-- If everything looks good, commit:
COMMIT;

-- If something went wrong, rollback:
-- ROLLBACK;
```
