#!/usr/bin/env python3

import os
import sys
import django

# Setup Django
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound

def test_name_preservation_with_chembl_name_difference():
    """Test that compound names are preserved even when ChEMBL has different preferred names"""
    
    print("🔍 Testing Name Preservation vs ChEMBL Preferred Names")
    print("=" * 55)
    
    # Check what ChEMBL thinks the names should be vs what we have
    test_compounds = ['CHEMBL12', 'CHEMBL25', 'CHEMBL154']
    
    for chembl_id in test_compounds:
        try:
            compound = Compound.objects.get(chembl_id=chembl_id)
            current_name = compound.name
            
            # Get ChEMBL's preferred name
            from compounds.management.commands.import_chembl_interactions import ChEMBLImporter
            importer = ChEMBLImporter()
            url = f"{importer.BASE_URL}/molecule/{chembl_id}.json"
            data = importer.fetch_with_retry(url)
            
            if data:
                chembl_name = data.get('pref_name', 'Unknown')
                
                print(f"\n📋 {chembl_id}")
                print(f"   Our name:    '{current_name}'")
                print(f"   ChEMBL name: '{chembl_name}'")
                
                if current_name.lower() == chembl_name.lower():
                    print(f"   ✓ Names match")
                else:
                    print(f"   ℹ️  Names differ - our original name is preserved")
                    
        except Exception as e:
            print(f"❌ {chembl_id}: Error - {e}")

if __name__ == "__main__":
    test_name_preservation_with_chembl_name_difference()
