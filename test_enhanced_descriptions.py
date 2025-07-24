#!/usr/bin/env python3
"""
Test script for enhanced compound descriptions
"""

import sys
import os

# Add Django project to Python path
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from compounds.management.commands.import_chembl_interactions import ChEMBLImporter, Command
from compounds.models import Compound

def test_description_generation():
    """Test the new description generation for compounds."""
    print("🧪 Testing Enhanced Description Generation\n")
    
    # Test with a known compound
    chembl_id = "CHEMBL12"  # Diazepam
    
    command = Command()
    importer = ChEMBLImporter(slow_mode=False)
    
    print(f"Testing with {chembl_id} (Diazepam)...")
    
    # Delete existing compound if it exists
    existing = Compound.objects.filter(chembl_id=chembl_id).first()
    if existing:
        print(f"Deleting existing compound: {existing.name}")
        existing.delete()
    
    # Create new compound with enhanced description
    try:
        compound = command.get_or_create_compound(importer, chembl_id, slow_mode=False)
        
        if compound:
            print(f"\n✅ COMPOUND CREATED: {compound.name}")
            print(f"📋 DESCRIPTION:\n{compound.description}")
            print(f"\n🏷️  CATEGORIES: {[cat.name for cat in compound.categories.all()]}")
            print(f"⚙️  MECHANISMS: {[(m.target_name.name, m.target_interaction) for m in compound.mechanism_of_action.all()]}")
        else:
            print("❌ Failed to create compound")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_description_generation()
