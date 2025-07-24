#!/usr/bin/env python3

import os
import sys
import django

# Setup Django
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound
from django.db.models import Q

def test_compound_search_with_aliases():
    """Test that compound search now works with aliases"""
    
    print("🔍 Testing Enhanced Compound Search with Aliases")
    print("=" * 55)
    
    # Test cases: search terms that should find compounds via aliases
    test_cases = [
        {
            'search_term': 'MK-0966',
            'expected_compound': 'Ketamine',
            'search_type': 'alias'
        },
        {
            'search_term': 'Aleve',
            'expected_compound': 'Fluoxetine',
            'search_type': 'alias'
        },
        {
            'search_term': 'Ketamine',
            'expected_compound': 'Ketamine',
            'search_type': 'name'
        },
        {
            'search_term': 'acetyl',
            'expected_compounds': ['Caffeine'],  # Should find via "Acetylsalicylic Acid"
            'search_type': 'partial_alias'
        }
    ]
    
    for test_case in test_cases:
        search_term = test_case['search_term']
        search_type = test_case['search_type']
        
        print(f"\n🔎 Testing '{search_term}' ({search_type} search)")
        
        # Perform the same search as the view
        results = Compound.objects.filter(
            Q(name__icontains=search_term) |
            Q(aliases__icontains=search_term)
        )
        
        print(f"   Found {results.count()} results:")
        
        for compound in results:
            print(f"     ✓ {compound.name}")
            if compound.aliases:
                print(f"       Aliases: {compound.aliases[:100]}...")
        
        # Check if expected compound(s) were found
        if 'expected_compound' in test_case:
            expected = test_case['expected_compound']
            found = any(compound.name == expected for compound in results)
            status = "✅ PASS" if found else "❌ FAIL"
            print(f"   {status} - Expected to find: {expected}")
        elif 'expected_compounds' in test_case:
            expected_list = test_case['expected_compounds']
            found_names = [compound.name for compound in results]
            all_found = all(expected in found_names for expected in expected_list)
            status = "✅ PASS" if all_found else "❌ FAIL"
            print(f"   {status} - Expected to find: {expected_list}")
    
    print(f"\n📊 Summary:")
    print(f"   Enhanced search now searches both:")
    print(f"     • Compound names (name__icontains)")
    print(f"     • Compound aliases (aliases__icontains)")
    print(f"   This allows finding compounds by their alternative names!")

if __name__ == "__main__":
    test_compound_search_with_aliases()
