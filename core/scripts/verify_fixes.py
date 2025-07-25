#!/usr/bin/env python
"""
Verification script to show the results of fixing unknown interactions
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, '/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import (
    CompoundToCompoundTargetInteraction, 
    CompoundTargetInteraction
)

def verify_mechanism_fixes():
    """Verify the mechanism fixes"""
    
    print("=== Compound-Target Mechanism Fix Results ===\n")
    
    all_mechanisms = CompoundTargetInteraction.objects.all()
    unknown_mechanisms = all_mechanisms.filter(mechanism='unknown')
    
    print(f"Total compound-target interactions: {all_mechanisms.count()}")
    print(f"Remaining unknown mechanisms: {unknown_mechanisms.count()}")
    print(f"Fixed mechanisms: {all_mechanisms.count() - unknown_mechanisms.count()}")
    print(f"Success rate: {((all_mechanisms.count() - unknown_mechanisms.count()) / all_mechanisms.count() * 100):.1f}%")
    
    print("\n=== Updated Mechanism Distribution ===")
    for choice in CompoundTargetInteraction.MECHANISM_CHOICES:
        count = all_mechanisms.filter(mechanism=choice[0]).count()
        if count > 0:
            print(f"{choice[1]}: {count}")

def verify_interaction_fixes():
    """Verify the compound-to-compound interaction fixes"""
    
    print("\n=== Compound-to-Compound Interaction Fix Results ===\n")
    
    all_interactions = CompoundToCompoundTargetInteraction.objects.all()
    unknown_interactions = all_interactions.filter(interaction_type='unknown')
    
    print(f"Total compound-to-compound interactions: {all_interactions.count()}")
    print(f"Remaining unknown interactions: {unknown_interactions.count()}")
    print(f"Fixed interactions: {all_interactions.count() - unknown_interactions.count()}")
    print(f"Success rate: {((all_interactions.count() - unknown_interactions.count()) / all_interactions.count() * 100):.1f}%")
    
    print("\n=== Updated Interaction Type Distribution ===")
    for choice in CompoundToCompoundTargetInteraction.INTERACTION_TYPE_CHOICES:
        count = all_interactions.filter(interaction_type=choice[0]).count()
        if count > 0:
            print(f"{choice[1]}: {count}")

def show_sample_fixes():
    """Show sample fixed interactions"""
    
    print("\n=== Sample Fixed Interactions ===\n")
    
    # Show sample compound-target mechanisms
    print("🧪 Sample Fixed Mechanisms:")
    fixed_mechanisms = CompoundTargetInteraction.objects.exclude(mechanism='unknown')[:5]
    for mech in fixed_mechanisms:
        print(f"   {mech.compound.name} → {mech.target.name}: {mech.get_mechanism_display()}")
    
    print("\n🔗 Sample Fixed Compound Interactions:")
    fixed_interactions = CompoundToCompoundTargetInteraction.objects.exclude(interaction_type='unknown')[:5]
    for interaction in fixed_interactions:
        print(f"   {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
        print(f"      Target: {interaction.target.name}")
        print(f"      Type: {interaction.get_interaction_type_display()}")
        print(f"      Description: {interaction.description[:80]}...")
        print()

def main():
    print("Unknown Interaction Fix Verification")
    print("=" * 40)
    
    verify_mechanism_fixes()
    verify_interaction_fixes()
    show_sample_fixes()
    
    print("\n✅ Verification complete!")

if __name__ == "__main__":
    main()
