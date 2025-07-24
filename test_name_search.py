#!/usr/bin/env python3
"""
Test script for ChEMBL name search functionality
"""

import sys
import os

# Add Django project to Python path
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from compounds.management.commands.import_chembl_interactions import ChEMBLImporter

def test_name_search():
    """Test the ChEMBL name search functionality."""
    print("🧪 Testing ChEMBL Name Search Functionality\n")
    
    # Initialize importer
    importer = ChEMBLImporter(slow_mode=False)
    
    # Test compounds with known names
    test_compounds = [
        "caffeine",      # Should find CHEMBL113
        "aspirin",       # Should find CHEMBL25
        "modafinil",     # Should find CHEMBL1373
        "ligandrol",     # Should find CHEMBL5170587 (SARM)
        "prozac",        # Should find fluoxetine
        "fakename123",   # Should not be found
    ]
    
    print("🔍 Individual Searches:")
    print("-" * 50)
    
    for compound_name in test_compounds:
        print(f"Searching for: {compound_name}")
        chembl_id = importer.get_compound_by_name(compound_name)
        
        if chembl_id:
            print(f"  ✅ Found: {compound_name} → {chembl_id}")
        else:
            print(f"  ❌ Not found: {compound_name}")
        print()
    
    print("\n🔍 Batch Search:")
    print("-" * 50)
    
    # Test batch search
    search_names = ["caffeine", "aspirin", "modafinil"]
    results = importer.search_compounds_by_names(search_names)
    
    print(f"Searched for: {search_names}")
    print("Results:")
    for name, chembl_id in results.items():
        print(f"  • {name} → {chembl_id}")
    
    if not results:
        print("  ❌ No results found")
    
    print(f"\n✅ Test completed! Found {len(results)}/{len(search_names)} compounds")

if __name__ == "__main__":
    test_name_search()
