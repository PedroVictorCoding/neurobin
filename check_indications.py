#!/usr/bin/env python3

import os
import sys
import django

# Setup Django
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound, CompoundCategories

def check_drug_indications():
    """Check if drug indication categories are properly assigned"""
    
    print("🔍 Checking Drug Indication Category Assignments")
    print("=" * 50)
    
    # Check our test compounds
    test_compounds = ['DIAZEPAM', 'Caffeine', 'Fluoxetine']
    
    for name in test_compounds:
        try:
            compound = Compound.objects.get(name=name)
            print(f"\n📋 {name} (ID: {compound.id}, ChEMBL: {compound.chembl_id})")
            
            categories = compound.categories.all()
            print(f"   Categories ({categories.count()}): {[cat.name for cat in categories]}")
            
            # Check for indication categories specifically
            indication_categories = compound.categories.filter(
                name__in=['Antiepileptic', 'Anxiolytic', 'Analgesic', 'Anti-inflammatory', 
                         'Antipyretic', 'Agitation Treatment', 'Arthralgia Treatment', 'Stroke Treatment']
            )
            print(f"   Drug Indications ({indication_categories.count()}): {[cat.name for cat in indication_categories]}")
            
        except Compound.DoesNotExist:
            print(f"\n❌ {name}: Not found")
        except Exception as e:
            print(f"\n❌ {name}: Error - {e}")
    
    print(f"\n📊 Total Categories in Database: {CompoundCategories.objects.count()}")
    print("   All Categories:")
    for cat in CompoundCategories.objects.all().order_by('name'):
        compound_count = cat.compounds.count()
        print(f"     • {cat.name}: {compound_count} compounds")

if __name__ == "__main__":
    check_drug_indications()
