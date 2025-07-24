#!/usr/bin/env python3

import os
import sys
import django

# Setup Django
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound

def test_name_normalization():
    """Test what compound names would look like after normalization"""
    
    print("🔍 Testing Compound Name Normalization")
    print("=" * 50)
    
    def normalize_compound_name(name: str) -> str:
        """Normalize compound name to proper capitalization."""
        if not name:
            return name
        
        # Handle special cases and acronyms that should stay uppercase
        special_cases = {
            'ATP': 'ATP',
            'ADP': 'ADP', 
            'DNA': 'DNA',
            'RNA': 'RNA',
            'GABA': 'GABA',
            'NADH': 'NADH',
            'NADPH': 'NADPH',
            'GTP': 'GTP',
            'GDP': 'GDP',
            'cAMP': 'cAMP',
            'cGMP': 'cGMP',
            'LSD': 'LSD',
            'MDMA': 'MDMA',
            'DMT': 'DMT',
        }
        
        # Check if it's a special case (exact match)
        if name.upper() in [key.upper() for key in special_cases.keys()]:
            for key, value in special_cases.items():
                if name.upper() == key.upper():
                    return value
        
        # Check if it looks like a compound code (contains numbers and/or hyphens in specific patterns)
        # e.g., AF710b, TAK-653, VK5211
        import re
        if re.match(r'^[A-Z]{1,5}[\d-]+[a-z]*$', name, re.IGNORECASE) or re.match(r'^[A-Z]{2,5}-\d+$', name, re.IGNORECASE):
            # Preserve compound codes as-is but ensure consistent capitalization
            # Keep letters uppercase and numbers/symbols as-is
            result = ""
            for i, char in enumerate(name):
                if char.isalpha():
                    # For compound codes, typically keep letters uppercase except for suffixes
                    if i > 0 and name[i-1].isdigit() and char.islower():
                        result += char.lower()  # Keep lowercase suffixes like 'b' in AF710b
                    else:
                        result += char.upper()
                else:
                    result += char
            return result
        
        # For regular drug names, capitalize first letter and lowercase the rest
        # But preserve capitalization after spaces, hyphens, and parentheses
        normalized = ""
        capitalize_next = True
        
        for char in name:
            if char in ' -()[]':
                normalized += char
                capitalize_next = True
            elif capitalize_next:
                normalized += char.upper()
                capitalize_next = False
            else:
                normalized += char.lower()
        
        return normalized
    
    # Get all compounds and show before/after normalization
    compounds = Compound.objects.all().order_by('name')
    
    changes_needed = []
    
    for compound in compounds:
        original = compound.name
        normalized = normalize_compound_name(original)
        
        if original != normalized:
            changes_needed.append((compound.id, original, normalized))
        
        status = "→" if original != normalized else "✓"
        print(f"  {status} '{original}' → '{normalized}'")
    
    print(f"\n📊 Summary:")
    print(f"   Total compounds: {compounds.count()}")
    print(f"   Need normalization: {len(changes_needed)}")
    
    if changes_needed:
        print(f"\n🔧 Compounds that would be normalized:")
        for comp_id, original, normalized in changes_needed:
            print(f"   ID {comp_id}: '{original}' → '{normalized}'")

if __name__ == "__main__":
    test_name_normalization()
