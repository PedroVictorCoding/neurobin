#!/usr/bin/env python
"""
Comprehensive script to fix unknown mechanisms and interactions
"""

import os
import sys
import django
from django.db import transaction

# Setup Django
sys.path.insert(0, '/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import (
    CompoundToCompoundTargetInteraction, 
    CompoundTargetInteraction, 
    Target,
    Compound
)

def analyze_unknown_mechanisms():
    """Analyze compound-target interactions with unknown mechanisms"""
    
    print("=== Analysis of Compound-Target Mechanisms ===\n")
    
    all_mechanisms = CompoundTargetInteraction.objects.all()
    unknown_mechanisms = all_mechanisms.filter(mechanism='unknown')
    
    print(f"Total compound-target interactions: {all_mechanisms.count()}")
    print(f"Unknown mechanisms: {unknown_mechanisms.count()}")
    print(f"Percentage unknown: {(unknown_mechanisms.count() / all_mechanisms.count() * 100):.1f}%")
    
    print("\n=== Mechanism Distribution ===")
    for choice in CompoundTargetInteraction.MECHANISM_CHOICES:
        count = all_mechanisms.filter(mechanism=choice[0]).count()
        print(f"{choice[1]}: {count}")
    
    return unknown_mechanisms

def get_target_specific_mechanism_suggestions():
    """Create target-specific mechanism suggestions based on target type and name"""
    
    suggestions = {
        # Cyclooxygenase targets - typically inhibitors
        'cyclooxygenase': 'inhibitor',
        'cox-1': 'inhibitor',
        'cox-2': 'inhibitor',
        'cyclooxygenase-1': 'inhibitor',
        'cyclooxygenase-2': 'inhibitor',
        
        # Receptors - typically agonists, antagonists, or modulators
        'dopamine': 'agonist',  # Default, but could be antagonist
        'serotonin': 'agonist',
        'gaba': 'agonist',
        'glutamate': 'antagonist',  # Many are antagonists
        'nmda': 'antagonist',
        'ampa': 'antagonist',
        'acetylcholine': 'agonist',
        'adrenergic': 'agonist',
        'histamine': 'antagonist',  # Many antihistamines
        
        # Enzymes - typically inhibitors
        'kinase': 'inhibitor',
        'phosphatase': 'inhibitor',
        'dehydrogenase': 'inhibitor',
        'reductase': 'inhibitor',
        'synthase': 'inhibitor',
        'transferase': 'inhibitor',
        
        # Ion channels - typically blockers or openers
        'sodium channel': 'blocker',
        'calcium channel': 'blocker',
        'potassium channel': 'blocker',
        'chloride channel': 'opener',
        
        # Transporters - typically inhibitors or substrates
        'transporter': 'inhibitor',
        'reuptake': 'inhibitor',
        'uptake': 'inhibitor',
    }
    
    return suggestions

def suggest_mechanism_from_target(target_name, compound_name=None):
    """Suggest mechanism based on target name and optionally compound name"""
    
    target_lower = target_name.lower()
    suggestions = get_target_specific_mechanism_suggestions()
    
    # Check each suggestion pattern
    for pattern, mechanism in suggestions.items():
        if pattern in target_lower:
            return mechanism
    
    # Compound-specific overrides
    if compound_name:
        compound_lower = compound_name.lower()
        
        # NSAIDs are typically COX inhibitors
        nsaids = ['ibuprofen', 'indomethacin', 'diclofenac', 'naproxen', 'ketorolac', 'celecoxib', 'etoricoxib']
        if any(nsaid in compound_lower for nsaid in nsaids):
            if 'cox' in target_lower or 'cyclooxygenase' in target_lower:
                return 'inhibitor'
        
        # Antipsychotics are typically dopamine antagonists
        antipsychotics = ['haloperidol', 'risperidone', 'olanzapine', 'quetiapine', 'aripiprazole']
        if any(ap in compound_lower for ap in antipsychotics):
            if 'dopamine' in target_lower:
                return 'antagonist'
        
        # Antidepressants - serotonin reuptake inhibitors
        antidepressants = ['fluoxetine', 'sertraline', 'paroxetine', 'citalopram', 'escitalopram']
        if any(ad in compound_lower for ad in antidepressants):
            if 'serotonin' in target_lower or 'sert' in target_lower:
                return 'inhibitor'
    
    # Default fallback
    return 'binder'  # Generic binding interaction

def fix_unknown_mechanisms(dry_run=True):
    """Fix unknown compound-target mechanisms"""
    
    print(f"\n=== {'DRY RUN: ' if dry_run else ''}Fixing Unknown Mechanisms ===\n")
    
    unknown_mechanisms = CompoundTargetInteraction.objects.filter(mechanism='unknown')
    fixed_count = 0
    
    for interaction in unknown_mechanisms[:20]:  # Limit for demonstration
        target_name = interaction.target.name
        compound_name = interaction.compound.name
        
        suggested_mechanism = suggest_mechanism_from_target(target_name, compound_name)
        
        print(f"✅ {compound_name} → {target_name}")
        print(f"   Current: unknown → Suggested: {suggested_mechanism}")
        
        if not dry_run:
            interaction.mechanism = suggested_mechanism
            interaction.save()
        
        fixed_count += 1
    
    total_unknown = unknown_mechanisms.count()
    if total_unknown > 20:
        print(f"\n... and {total_unknown - 20} more interactions")
    
    print(f"\n{'Would fix' if dry_run else 'Fixed'} {min(fixed_count, total_unknown)} of {total_unknown} unknown mechanisms")
    
    return fixed_count

def fix_compound_interactions_from_mechanisms():
    """Fix compound-to-compound interactions based on updated mechanisms"""
    
    print("\n=== Fixing Compound-to-Compound Interactions ===\n")
    
    unknown_interactions = CompoundToCompoundTargetInteraction.objects.filter(interaction_type='unknown')
    fixed_count = 0
    
    interaction_rules = {
        # Antagonistic combinations
        ('agonist', 'antagonist'): 'antagonistic',
        ('agonist', 'inverse_agonist'): 'antagonistic', 
        ('activator', 'inhibitor'): 'antagonistic',
        
        # Competitive combinations
        ('agonist', 'agonist'): 'competitive',
        ('antagonist', 'antagonist'): 'competitive',
        ('agonist', 'partial_agonist'): 'competitive',
        
        # Additive combinations
        ('inhibitor', 'inhibitor'): 'additive',
        ('blocker', 'blocker'): 'additive',
        
        # Synergistic combinations
        ('agonist', 'pam'): 'synergistic',  # PAM enhances agonist
        ('activator', 'activator'): 'synergistic',
    }
    
    for interaction in unknown_interactions[:10]:  # Sample for demonstration
        mechanisms_a = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_a,
            target=interaction.target
        )
        
        mechanisms_b = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_b,
            target=interaction.target
        )
        
        if mechanisms_a.exists() and mechanisms_b.exists():
            mech_a = mechanisms_a.first().mechanism
            mech_b = mechanisms_b.first().mechanism
            
            # Check interaction rules
            suggested_type = None
            for (m1, m2), interaction_type in interaction_rules.items():
                if (mech_a == m1 and mech_b == m2) or (mech_a == m2 and mech_b == m1):
                    suggested_type = interaction_type
                    break
            
            if suggested_type:
                print(f"✅ {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
                print(f"   Target: {interaction.target.name}")
                print(f"   Mechanisms: {mech_a} vs {mech_b} → {suggested_type}")
                
                interaction.interaction_type = suggested_type
                interaction.save()
                fixed_count += 1
    
    print(f"\nFixed {fixed_count} compound-to-compound interactions")

def main():
    print("Comprehensive Unknown Interaction Fix Tool")
    print("=" * 50)
    
    # Step 1: Analyze current state
    unknown_mechanisms = analyze_unknown_mechanisms()
    
    if unknown_mechanisms.count() > 0:
        # Step 2: Fix unknown mechanisms first
        fix_count = fix_unknown_mechanisms(dry_run=True)
        
        if fix_count > 0:
            response = input(f"\nFix {min(fix_count, unknown_mechanisms.count())} unknown mechanisms? (yes/no): ").lower().strip()
            if response == 'yes':
                with transaction.atomic():
                    fix_unknown_mechanisms(dry_run=False)
                    print("\n✅ Mechanisms fixed!")
                    
                    # Step 3: Now fix compound-to-compound interactions
                    fix_compound_interactions_from_mechanisms()
            else:
                print("Fixes cancelled.")
    else:
        print("\n✅ No unknown mechanisms found!")

if __name__ == "__main__":
    main()
