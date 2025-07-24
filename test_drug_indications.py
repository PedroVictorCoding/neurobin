#!/usr/bin/env python3
"""
Test ChEMBL drug indications API
"""

import sys
import os
import requests
import json

# Add Django project to Python path
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from compounds.management.commands.import_chembl_interactions import ChEMBLImporter

def test_indications():
    """Test ChEMBL drug indications API."""
    print("🧪 Testing ChEMBL Drug Indications API\n")
    
    # Test compounds known to have drug indications
    test_compounds = [
        ("CHEMBL12", "Diazepam"),
        ("CHEMBL796", "Methylphenidate"), 
        ("CHEMBL25", "Caffeine"),
        ("CHEMBL154", "Fluoxetine"),
        ("CHEMBL521", "Ibuprofen"),
    ]
    
    importer = ChEMBLImporter(slow_mode=False)
    
    for chembl_id, name in test_compounds:
        print(f"🔍 Testing {name} ({chembl_id})")
        print("-" * 50)
        
        # Test direct API call
        url = f"https://www.ebi.ac.uk/chembl/api/data/drug_indication.json"
        params = {'molecule_chembl_id': chembl_id, 'limit': 10}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            print(f"API Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                indications = data.get('drug_indications', [])
                print(f"Found {len(indications)} indications")
                
                for i, indication in enumerate(indications[:3]):
                    print(f"  {i+1}. {indication.get('indication', 'Unknown')}")
                    print(f"     Phase: {indication.get('max_phase_for_ind', 'N/A')}")
                    print(f"     EFO ID: {indication.get('efo_id', 'N/A')}")
                
                # Test our method
                our_indications = importer.get_drug_indications(chembl_id)
                print(f"\nOur method found: {len(our_indications)} indications")
                
            else:
                print(f"API Error: {response.status_code}")
                print(f"Response: {response.text[:200]}")
                
        except Exception as e:
            print(f"Error: {e}")
        
        print("\n")

if __name__ == "__main__":
    test_indications()
