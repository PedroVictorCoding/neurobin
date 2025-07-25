#!/usr/bin/env python
"""
Script to analyze and fix compound-to-compound interactions with unknown relations
"""

import os
import sys
import django
from django.db import transaction

# Setup Django
sys.path.insert(0, '/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import CompoundToCompoundTargetInteraction, CompoundTargetInteraction

def analyze_unknown_interactions():
    """Analyze current compound-to-compound interactions with unknown relations"""
    
    print("=== Analysis of Compound-to-Compound Interactions ===\n")
    
    # Get all interactions
    all_interactions = CompoundToCompoundTargetInteraction.objects.all()
    unknown_interactions = all_interactions.filter(interaction_type='unknown')
    
    print(f"Total compound-to-compound interactions: {all_interactions.count()}")
    print(f"Unknown interactions: {unknown_interactions.count()}")
    
    if unknown_interactions.count() == 0:
        print("✅ No unknown interactions found!")
        return
    
    print(f"Percentage unknown: {(unknown_interactions.count() / all_interactions.count() * 100):.1f}%")
    
    print("\n=== Interaction Type Distribution ===")
    for choice in CompoundToCompoundTargetInteraction.INTERACTION_TYPE_CHOICES:
        count = all_interactions.filter(interaction_type=choice[0]).count()
        print(f"{choice[1]}: {count}")
    
    print("\n=== Sample Unknown Interactions ===")
    for interaction in unknown_interactions[:10]:
        print(f"- {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
        print(f"  Target: {interaction.target.name}")
        print(f"  Description: {interaction.description[:100]}...")
        print()

def analyze_target_mechanisms():
    """Analyze the mechanisms of compounds that have unknown interactions"""
    
    print("\n=== Analysis of Target Mechanisms for Unknown Interactions ===\n")
    
    unknown_interactions = CompoundToCompoundTargetInteraction.objects.filter(interaction_type='unknown')
    
    for interaction in unknown_interactions[:5]:
        print(f"Interaction: {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
        print(f"Target: {interaction.target.name}")
        
        # Get mechanisms for compound A
        mechanisms_a = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_a,
            target=interaction.target
        )
        
        # Get mechanisms for compound B  
        mechanisms_b = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_b,
            target=interaction.target
        )
        
        print(f"  {interaction.compound_a.name} mechanisms:")
        for mech in mechanisms_a:
            print(f"    - {mech.mechanism} (affinity: {mech.affinity_level})")
            
        print(f"  {interaction.compound_b.name} mechanisms:")
        for mech in mechanisms_b:
            print(f"    - {mech.mechanism} (affinity: {mech.affinity_level})")
        
        print()

def suggest_interaction_types(compound_a_mechanisms, compound_b_mechanisms):
    """Suggest interaction type based on compound mechanisms"""
    
    # Extract mechanism types
    mech_a = [m.mechanism for m in compound_a_mechanisms]
    mech_b = [m.mechanism for m in compound_b_mechanisms]
    
    # Define interaction rules
    antagonistic_pairs = [
        ('agonist', 'antagonist'),
        ('agonist', 'inverse_agonist'),
        ('activator', 'inhibitor'),
        ('pam', 'nam'),  # Positive vs Negative Allosteric Modulator
    ]
    
    competitive_mechanisms = [
        'agonist', 'partial_agonist', 'antagonist', 'inverse_agonist'
    ]
    
    synergistic_pairs = [
        ('pam', 'agonist'),  # PAM enhances agonist effect
        ('activator', 'activator'),  # Both activate
        ('agonist', 'agonist'),  # Both agonists (may be additive/synergistic)
    ]
    
    # Check for antagonistic interactions
    for mech_a_item in mech_a:
        for mech_b_item in mech_b:
            if (mech_a_item, mech_b_item) in antagonistic_pairs or (mech_b_item, mech_a_item) in antagonistic_pairs:
                return 'antagonistic'
    
    # Check for competitive interactions (same receptor, similar mechanisms)
    if any(m in competitive_mechanisms for m in mech_a) and any(m in competitive_mechanisms for m in mech_b):
        return 'competitive'
    
    # Check for synergistic interactions
    for mech_a_item in mech_a:
        for mech_b_item in mech_b:
            if (mech_a_item, mech_b_item) in synergistic_pairs or (mech_b_item, mech_a_item) in synergistic_pairs:
                return 'synergistic'
    
    # If both are inhibitors, might be additive
    if 'inhibitor' in mech_a and 'inhibitor' in mech_b:
        return 'additive'
    
    # Default fallback
    return 'unknown'

def fix_unknown_interactions(dry_run=True):
    """Fix unknown interactions by inferring from compound mechanisms"""
    
    print(f"\n=== {'DRY RUN: ' if dry_run else ''}Fixing Unknown Interactions ===\n")
    
    unknown_interactions = CompoundToCompoundTargetInteraction.objects.filter(interaction_type='unknown')
    
    fixed_count = 0
    
    for interaction in unknown_interactions:
        # Get mechanisms for both compounds on the shared target
        mechanisms_a = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_a,
            target=interaction.target
        )
        
        mechanisms_b = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_b,
            target=interaction.target
        )
        
        if mechanisms_a.exists() and mechanisms_b.exists():
            suggested_type = suggest_interaction_types(mechanisms_a, mechanisms_b)
            
            if suggested_type != 'unknown':
                print(f"✅ {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
                print(f"   Target: {interaction.target.name}")
                print(f"   Current: unknown → Suggested: {suggested_type}")
                print(f"   Mechanisms A: {[m.mechanism for m in mechanisms_a]}")
                print(f"   Mechanisms B: {[m.mechanism for m in mechanisms_b]}")
                
                if not dry_run:
                    interaction.interaction_type = suggested_type
                    interaction.save()
                
                fixed_count += 1
                print()
        else:
            print(f"⚠️  {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
            print(f"   Target: {interaction.target.name}")
            print(f"   Missing mechanism data - keeping as unknown")
            print()
    
    print(f"{'Would fix' if dry_run else 'Fixed'} {fixed_count} interactions")
    
    return fixed_count

def main():
    print("Compound-to-Compound Interaction Analysis and Fix Tool")
    print("=" * 60)
    
    # Step 1: Analyze current state
    analyze_unknown_interactions()
    
    # Step 2: Analyze mechanisms for unknown interactions
    analyze_target_mechanisms()
    
    # Step 3: Dry run fix
    fix_count = fix_unknown_interactions(dry_run=True)
    
    if fix_count > 0:
        response = input(f"\nFound {fix_count} interactions that can be fixed. Apply fixes? (yes/no): ").lower().strip()
        if response == 'yes':
            with transaction.atomic():
                fix_unknown_interactions(dry_run=False)
                print("\n✅ Fixes applied successfully!")
        else:
            print("Fixes cancelled.")
    else:
        print("\n✅ No unknown interactions need fixing.")

if __name__ == "__main__":
    main()
