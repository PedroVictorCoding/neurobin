# Neurobin Database Management Scripts

This folder contains utility scripts for database maintenance, cleanup, and analysis tasks.

## 📁 Scripts Overview

### 🧹 Database Cleanup Scripts

#### `cleanup_organisms.py`
**Purpose**: Remove non-Homo sapiens organisms and blacklisted mechanisms  
**Usage**: `/home/main/Dev/neurobin/venv/bin/python cleanup_organisms.py`  
**Features**:
- Interactive confirmation before making changes
- Removes all targets that aren't Homo sapiens
- Removes compound mechanisms for blacklisted organisms
- Transaction-safe with rollback on errors
- Shows before/after statistics

#### `cleanup_organisms.sql`
**Purpose**: Raw SQL queries for organism cleanup (reference only)  
**Usage**: Manual execution in SQLite shell  
**Note**: Use the Python script instead for safety

### 🔧 Interaction Fixing Scripts

#### `fix_unknown_interactions.py`
**Purpose**: Initial analysis tool for compound-to-compound interactions  
**Usage**: `/home/main/Dev/neurobin/venv/bin/python fix_unknown_interactions.py`  
**Features**:
- Analyzes unknown interaction distribution
- Shows sample problematic interactions
- Dry-run capability for safe testing

#### `comprehensive_interaction_fix.py`
**Purpose**: Enhanced mechanism suggestion system  
**Usage**: `/home/main/Dev/neurobin/venv/bin/python comprehensive_interaction_fix.py`  
**Features**:
- Target-specific mechanism suggestions
- Compound-specific pharmacological rules
- Interactive fixing with confirmation

#### `batch_fix_unknowns.py`
**Purpose**: Production batch processor for fixing unknown mechanisms and interactions  
**Usage**: `/home/main/Dev/neurobin/venv/bin/python batch_fix_unknowns.py`  
**Features**:
- Processes all unknown mechanisms in batches
- Intelligent pharmacological rule engine
- Fixes compound-to-compound interactions based on mechanisms
- Transaction-safe batch processing

### 📊 Verification & Analysis Scripts

#### `verify_fixes.py`
**Purpose**: Verification and results display for interaction fixes  
**Usage**: `/home/main/Dev/neurobin/venv/bin/python verify_fixes.py`  
**Features**:
- Shows before/after statistics
- Displays mechanism and interaction distributions
- Sample fixed interactions showcase

## 📋 Summary Documents

#### `ORGANISM_CLEANUP_SUMMARY.md`
Complete summary of organism cleanup operation including:
- Before/after statistics
- List of removed organisms
- Database impact analysis

#### `INTERACTION_FIX_SUMMARY.md`
Comprehensive summary of interaction fix operation including:
- Mechanism fix results (63% success rate)
- Interaction fix results (32% success rate)
- Pharmacological rules applied
- Examples of fixed interactions

## 🚀 Quick Start Guide

### 1. Database Cleanup (One-time setup)
```bash
cd /home/main/Dev/neurobin/core
/home/main/Dev/neurobin/venv/bin/python scripts/cleanup_organisms.py
```

### 2. Fix Unknown Interactions (Data quality improvement)
```bash
cd /home/main/Dev/neurobin/core
/home/main/Dev/neurobin/venv/bin/python scripts/batch_fix_unknowns.py
```

### 3. Verify Results
```bash
cd /home/main/Dev/neurobin/core
/home/main/Dev/neurobin/venv/bin/python scripts/verify_fixes.py
```

## ⚠️ Important Notes

- **Always backup your database** before running cleanup scripts
- All scripts include interactive confirmations for safety
- Scripts use Django ORM for database-safe operations
- Run scripts from the `/home/main/Dev/neurobin/core` directory
- Ensure the virtual environment is activated

## 🔄 Execution Order

For a fresh database setup, run scripts in this order:
1. `cleanup_organisms.py` - Remove non-human data
2. `batch_fix_unknowns.py` - Fix unknown interactions
3. `verify_fixes.py` - Confirm results

## 📈 Results Achieved

- **Organism Cleanup**: Reduced database by ~45%, focused on human-relevant data
- **Interaction Fixes**: Fixed 271 mechanisms + 313 interactions (584 total improvements)
- **Data Quality**: Improved from 96.1% unknown interactions to 67.8%

*Scripts created and organized on July 25, 2025*
