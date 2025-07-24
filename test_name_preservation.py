#!/usr/bin/env python3

import os
import sys
import django

# Setup Django
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound

def test_name_preservation():
    """Test that compound names are preserved during updates"""
    
    print("🔍 Testing Compound Name Preservation During Updates")
    print("=" * 55)
    
    # Check our test compounds before and after import
    test_compounds = [
        {'chembl_id': 'CHEMBL12', 'expected_preserved_name': 'DIAZEPAM'},
        {'chembl_id': 'CHEMBL25', 'expected_preserved_name': 'Caffeine'},
        {'chembl_id': 'CHEMBL154', 'expected_preserved_name': 'Fluoxetine'}
    ]
    
    print("Checking if names were preserved...")
    for test_case in test_compounds:
        try:
            compound = Compound.objects.get(chembl_id=test_case['chembl_id'])
            current_name = compound.name
            expected_name = test_case['expected_preserved_name']
            
            if current_name == expected_name:
                print(f"✓ {test_case['chembl_id']}: Name preserved correctly: '{current_name}'")
            else:
                print(f"❌ {test_case['chembl_id']}: Name changed from expected!")
                print(f"   Expected: '{expected_name}'")
                print(f"   Current:  '{current_name}'")
                
                # Let's see what ChEMBL thinks the name should be
                from compounds.management.commands.import_chembl_interactions import ChEMBLImporter
                importer = ChEMBLImporter()
                url = f"{importer.BASE_URL}/molecule/{test_case['chembl_id']}.json"
                data = importer.fetch_with_retry(url)
                if data:
                    chembl_name = data.get('pref_name', 'Unknown')
                    print(f"   ChEMBL name: '{chembl_name}'")
                
        except Compound.DoesNotExist:
            print(f"❌ {test_case['chembl_id']}: Compound not found")
        except Exception as e:
            print(f"❌ {test_case['chembl_id']}: Error - {e}")

if __name__ == "__main__":
    test_name_preservation()
