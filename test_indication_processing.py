#!/usr/bin/env python3

import os
import sys
import django

# Setup Django
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.management.commands.import_chembl_interactions import ChEMBLImporter, Command

def test_indication_processing():
    """Test the updated drug indication processing"""
    
    print("🧪 Testing Updated Drug Indication Processing")
    print("=" * 50)
    
    # Create importer and command instance
    importer = ChEMBLImporter()
    command = Command()
    
    # Test compounds
    test_compounds = [
        ('CHEMBL12', 'Diazepam'),
        ('CHEMBL154', 'Fluoxetine'),
        ('CHEMBL521', 'Ibuprofen'),
    ]
    
    for chembl_id, name in test_compounds:
        print(f"\n🔍 Testing {name} ({chembl_id})")
        print("-" * 40)
        
        # Get raw indications
        indications = importer.get_drug_indications(chembl_id)
        print(f"Found {len(indications)} indications:")
        
        for i, indication_data in enumerate(indications, 1):
            # Extract indication name using the same logic as the updated code
            indication = (
                indication_data.get('efo_term', '') or
                indication_data.get('mesh_heading', '') or
                indication_data.get('indication', '')
            )
            
            phase = indication_data.get('max_phase_for_ind', 'N/A')
            efo_id = indication_data.get('efo_id', 'N/A')
            
            print(f"  {i}. Raw: '{indication}' (Phase {phase}, EFO: {efo_id})")
            
            # Test formatting
            if indication:
                category_name = command._format_indication_category(indication)
                print(f"     → Category: '{category_name}'")
            else:
                print(f"     → No indication text found")

if __name__ == "__main__":
    test_indication_processing()
