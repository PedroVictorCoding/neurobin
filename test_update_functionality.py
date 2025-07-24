#!/usr/bin/env python3
"""
Test script for enhanced compound updating functionality
"""

import sys
import os

# Add Django project to Python path
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from compounds.models import Compound

def test_update_functionality():
    """Test the new update functionality for compounds."""
    print("🧪 Testing Enhanced Compound Update Functionality\n")
    
    # Show current state of compounds
    print("📋 Current Compound Database State:")
    print("=" * 60)
    
    all_compounds = Compound.objects.all()
    for compound in all_compounds:
        chembl_status = f"ChEMBL: {compound.chembl_id}" if compound.chembl_id else "No ChEMBL ID"
        categories = [cat.name for cat in compound.categories.all()]
        category_status = f"Categories: {len(categories)}" if categories else "No categories"
        
        description_type = "Enhanced" if not compound.description.startswith("ChEMBL ID:") else "Technical"
        if "Imported from ChEMBL" in compound.description:
            description_type = "Technical"
        
        print(f"• {compound.name[:30]:<30} | {chembl_status:<15} | {category_status:<15} | Desc: {description_type}")
    
    print(f"\n📊 Summary:")
    with_chembl = Compound.objects.filter(chembl_id__isnull=False).exclude(chembl_id='')
    without_chembl = Compound.objects.filter(chembl_id__isnull=True)
    with_categories = Compound.objects.filter(categories__isnull=False).distinct()
    
    print(f"• Total compounds: {all_compounds.count()}")
    print(f"• With ChEMBL ID: {with_chembl.count()}")
    print(f"• Without ChEMBL ID: {without_chembl.count()}")
    print(f"• With categories: {with_categories.count()}")
    
    # Show upgrade opportunities
    old_descriptions = Compound.objects.filter(description__contains="ChEMBL ID:")
    import_descriptions = Compound.objects.filter(description__contains="Imported from ChEMBL")
    
    print(f"\n🔄 Update Opportunities:")
    print(f"• Compounds with old technical descriptions: {old_descriptions.count()}")
    print(f"• Compounds with import-style descriptions: {import_descriptions.count()}")
    print(f"• Compounds that could be enhanced: {old_descriptions.count() + import_descriptions.count()}")
    
    print(f"\n💡 Recommended Commands:")
    print("  # Update all compounds with ChEMBL IDs:")
    print("  python manage.py import_chembl_interactions --all-compounds --update-existing")
    print("\n  # Find and update compounds by name matching:")
    print("  python manage.py import_chembl_interactions --update-existing --match-by-name")
    print("\n  # Update specific compounds:")
    print("  python manage.py import_chembl_interactions --compounds=CHEMBL796,CHEMBL405 --update-existing")

if __name__ == "__main__":
    test_update_functionality()
