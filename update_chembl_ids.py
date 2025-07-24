#!/usr/bin/env python
"""
Quick script to update compounds with ChEMBL IDs for testing the import system.
"""

import os
import sys
import django

# Setup Django environment
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound

def update_compound_chembl_ids():
    """Update existing compounds with ChEMBL IDs."""
    compounds_data = [
        ('Caffeine', 'CHEMBL25'),
        ('Fluoxetine', 'CHEMBL154'), 
        ('Modafinil', 'CHEMBL1487'),
        ('LSD', 'CHEMBL112'),
        ('Ketamine', 'CHEMBL122')
    ]
    
    print("Updating compounds with ChEMBL IDs...")
    
    for name, chembl_id in compounds_data:
        try:
            compound = Compound.objects.get(name=name)
            compound.chembl_id = chembl_id
            compound.save()
            print(f"[✓] Updated {name} with ChEMBL ID: {chembl_id}")
        except Compound.DoesNotExist:
            print(f"[!] Compound {name} not found")
    
    print("\nCurrent compounds with ChEMBL IDs:")
    for compound in Compound.objects.filter(chembl_id__isnull=False):
        print(f"  {compound.name} ({compound.chembl_id})")

if __name__ == '__main__':
    update_compound_chembl_ids()
