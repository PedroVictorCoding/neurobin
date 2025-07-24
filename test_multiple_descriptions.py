#!/usr/bin/env python3
"""
Test multiple compounds for enhanced descriptions
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

def test_multiple_compounds():
    """Test description generation for different types of compounds."""
    print("🧪 Testing Multiple Compound Descriptions\n")
    
    test_compounds = [
        ("CHEMBL25", "Caffeine"),
        ("CHEMBL796", "Methylphenidate"), 
        ("CHEMBL405", "Amphetamine"),
    ]
    
    command = Command()
    importer = ChEMBLImporter(slow_mode=False)
    
    for chembl_id, expected_name in test_compounds:
        print(f"\n{'='*60}")
        print(f"🔬 Testing {expected_name} ({chembl_id})")
        print('='*60)
        
        # Get existing compound
        compound = Compound.objects.filter(chembl_id=chembl_id).first()
        
        if not compound:
            print(f"Creating new compound...")
            try:
                compound = command.get_or_create_compound(importer, chembl_id, slow_mode=False)
            except Exception as e:
                print(f"❌ Error creating compound: {e}")
                continue
        
        if compound:
            print(f"✅ COMPOUND: {compound.name}")
            print(f"📋 DESCRIPTION:")
            print(f"   {compound.description}")
            print(f"🏷️  CATEGORIES: {[cat.name for cat in compound.categories.all()]}")
            
            mechanisms = [(m.target_name.name, m.target_interaction) for m in compound.mechanism_of_action.all()]
            if mechanisms:
                print(f"⚙️  MECHANISMS:")
                for target, interaction in mechanisms[:3]:  # Show first 3
                    print(f"   • {target} ({interaction})")
                if len(mechanisms) > 3:
                    print(f"   ... and {len(mechanisms)-3} more")
            else:
                print("⚙️  MECHANISMS: None found")
        else:
            print("❌ Compound not found/created")

if __name__ == "__main__":
    test_multiple_compounds()
