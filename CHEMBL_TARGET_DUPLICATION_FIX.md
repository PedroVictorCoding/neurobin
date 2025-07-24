# ChEMBL Import Target Duplication Fix

## 🐛 **Issue Identified**

The ChEMBL import was failing with:
```
[✗] Error creating target CHEMBL238: UNIQUE constraint failed: compounds_target.name
```

## 🔧 **Root Cause**

The `get_or_create_target()` method was using `Target.objects.create()` instead of `get_or_create()`, causing duplicate name violations when:
1. A target already existed with the same name but no ChEMBL ID
2. Multiple ChEMBL targets had the same preferred name
3. Targets were being processed multiple times

## ✅ **Solution Implemented**

### Enhanced Target Creation Logic:

1. **Primary Check**: Look for existing target by ChEMBL ID
2. **Secondary Check**: Look for existing target by name (without ChEMBL ID)
3. **Update Existing**: If found by name, update with ChEMBL data
4. **Safe Creation**: Use `get_or_create()` instead of `create()`
5. **Unique Name Handling**: If name conflicts, append ChEMBL ID to make unique
6. **Fallback Recovery**: If creation fails, try to find existing target by name

### Key Improvements:

```python
# Before (problematic)
target = Target.objects.create(...)

# After (robust)
target, created = Target.objects.get_or_create(
    chembl_id=target_chembl_id,
    defaults={...}
)

# Handle name conflicts
if Target.objects.filter(name=target_name).exclude(id=target.id).exists():
    unique_name = f"{target_name} ({target_chembl_id})"
    target.name = unique_name
    target.save()
```

## 🧪 **Testing Results**

✅ **Fixed**: methylphenidate import now works without target duplication errors
✅ **Enhanced**: Existing targets get updated with ChEMBL data  
✅ **Robust**: Multiple compounds can share targets without conflicts
✅ **Fallback**: Graceful handling of constraint violations

## 📊 **Example Success**

```bash
# Before (error)
[✗] Error creating target CHEMBL238: UNIQUE constraint failed: compounds_target.name

# After (success)
[✓] Updated existing target with ChEMBL data: Dopamine transporter
[→] Created target: Norepinephrine transporter (single protein)
[✓] Created interaction: METHYLPHENIDATE → Dopamine transporter (inhibitor)
```

The system now robustly handles target creation and updates without constraint violations! 🎉
