#!/usr/bin/env python
"""
Batch fix for all unknown mechanisms and interactions with improved logic
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

def get_improved_mechanism_suggestions():
    """Improved mechanism suggestions based on pharmacology"""
    
    # Compound-specific mechanisms
    compound_mechanisms = {
        # NSAIDs - COX inhibitors
        'ibuprofen': {'cyclooxygenase': 'inhibitor', 'cox': 'inhibitor'},
        'indomethacin': {'cyclooxygenase': 'inhibitor', 'cox': 'inhibitor'},
        'diclofenac': {'cyclooxygenase': 'inhibitor', 'cox': 'inhibitor'},
        'ketorolac': {'cyclooxygenase': 'inhibitor', 'cox': 'inhibitor'},
        'celecoxib': {'cyclooxygenase-2': 'inhibitor', 'cox-2': 'inhibitor'},
        'etoricoxib': {'cyclooxygenase-2': 'inhibitor', 'cox-2': 'inhibitor'},
        
        # Antidepressants - reuptake inhibitors
        'fluoxetine': {'serotonin': 'inhibitor', 'transporter': 'inhibitor'},
        'sertraline': {'serotonin': 'inhibitor', 'transporter': 'inhibitor'},
        'paroxetine': {'serotonin': 'inhibitor', 'transporter': 'inhibitor'},
        'venlafaxine': {'serotonin': 'inhibitor', 'norepinephrine': 'inhibitor', 'transporter': 'inhibitor'},
        
        # Stimulants
        'methylphenidate': {'dopamine': 'inhibitor', 'transporter': 'inhibitor'},
        'amphetamine': {'dopamine': 'substrate', 'transporter': 'substrate'},
        
        # NMDA antagonists
        'ketamine': {'nmda': 'antagonist', 'glutamate': 'antagonist'},
        'memantine': {'nmda': 'antagonist', 'glutamate': 'antagonist'},
        
        # Benzodiazepines - GABA PAMs
        'diazepam': {'gaba': 'pam', 'benzodiazepine': 'agonist'},
        'lorazepam': {'gaba': 'pam', 'benzodiazepine': 'agonist'},
        'alprazolam': {'gaba': 'pam', 'benzodiazepine': 'agonist'},
        
        # Antipsychotics - dopamine antagonists
        'haloperidol': {'dopamine': 'antagonist'},
        'risperidone': {'dopamine': 'antagonist', 'serotonin': 'antagonist'},
        'olanzapine': {'dopamine': 'antagonist', 'serotonin': 'antagonist'},
        
        # Opioids - mu-opioid agonists
        'morphine': {'opioid': 'agonist', 'mu': 'agonist'},
        'fentanyl': {'opioid': 'agonist', 'mu': 'agonist'},
        'tramadol': {'opioid': 'agonist', 'serotonin': 'inhibitor'},
    }
    
    # Target-specific default mechanisms
    target_defaults = {
        'cyclooxygenase': 'inhibitor',
        'cox': 'inhibitor',
        'serotonin transporter': 'inhibitor',
        'dopamine transporter': 'inhibitor',
        'norepinephrine transporter': 'inhibitor',
        'serotonin receptor': 'agonist',
        'dopamine receptor': 'agonist',
        'adrenergic receptor': 'agonist',
        'gaba receptor': 'agonist',
        'glutamate receptor': 'antagonist',
        'nmda receptor': 'antagonist',
        'ampa receptor': 'antagonist',
        'cytochrome p450': 'substrate',
        'carbonic anhydrase': 'inhibitor',
        'acetylcholinesterase': 'inhibitor',
        'monoamine oxidase': 'inhibitor',
        'sodium channel': 'blocker',
        'calcium channel': 'blocker',
        'potassium channel': 'blocker',
        'kinase': 'inhibitor',
        'phosphatase': 'inhibitor',
    }
    
    return compound_mechanisms, target_defaults

def suggest_mechanism(compound_name, target_name):
    """Suggest mechanism based on compound and target"""
    
    compound_mechanisms, target_defaults = get_improved_mechanism_suggestions()
    
    compound_lower = compound_name.lower()
    target_lower = target_name.lower()
    
    # Check compound-specific mechanisms first
    for compound_pattern, mechanisms in compound_mechanisms.items():
        if compound_pattern in compound_lower:
            for target_pattern, mechanism in mechanisms.items():
                if target_pattern in target_lower:
                    return mechanism
    
    # Check target-specific defaults
    for target_pattern, mechanism in target_defaults.items():
        if target_pattern in target_lower:
            return mechanism
    
    # Special cases for transporters
    if 'transporter' in target_lower or 'reuptake' in target_lower:
        # Most compounds that interact with transporters are inhibitors
        return 'inhibitor'
    
    # Special cases for receptors
    if 'receptor' in target_lower:
        # Default to agonist for receptors unless it's a known antagonist drug
        antagonist_drugs = ['haloperidol', 'risperidone', 'olanzapine', 'quetiapine', 'aripiprazole']
        if any(drug in compound_lower for drug in antagonist_drugs):
            return 'antagonist'
        return 'agonist'
    
    # Default fallback
    return 'binder'

def batch_fix_mechanisms(batch_size=100):
    """Fix unknown mechanisms in batches"""
    
    print("=== Batch Fixing All Unknown Mechanisms ===\n")
    
    unknown_mechanisms = CompoundTargetInteraction.objects.filter(mechanism='unknown')
    total_count = unknown_mechanisms.count()
    
    print(f"Total unknown mechanisms to fix: {total_count}")
    
    fixed_count = 0
    
    # Process in batches
    for i in range(0, total_count, batch_size):
        batch = unknown_mechanisms[i:i+batch_size]
        
        with transaction.atomic():
            for interaction in batch:
                suggested_mechanism = suggest_mechanism(
                    interaction.compound.name, 
                    interaction.target.name
                )
                
                interaction.mechanism = suggested_mechanism
                interaction.save()
                fixed_count += 1
        
        print(f"Fixed batch {i//batch_size + 1}: {min(i+batch_size, total_count)}/{total_count}")
    
    print(f"\n✅ Fixed {fixed_count} unknown mechanisms!")
    
    return fixed_count

def batch_fix_interactions():
    """Fix compound-to-compound interactions based on updated mechanisms"""
    
    print("\n=== Fixing Compound-to-Compound Interactions ===\n")
    
    unknown_interactions = CompoundToCompoundTargetInteraction.objects.filter(interaction_type='unknown')
    total_count = unknown_interactions.count()
    
    print(f"Total unknown interactions to fix: {total_count}")
    
    # Interaction logic rules
    interaction_rules = {
        # Antagonistic - opposing mechanisms
        ('agonist', 'antagonist'): 'antagonistic',
        ('agonist', 'inverse_agonist'): 'antagonistic',
        ('activator', 'inhibitor'): 'antagonistic',
        ('opener', 'blocker'): 'antagonistic',
        
        # Competitive - same mechanism type
        ('agonist', 'agonist'): 'competitive',
        ('antagonist', 'antagonist'): 'competitive',
        ('agonist', 'partial_agonist'): 'competitive',
        ('binder', 'binder'): 'competitive',
        
        # Additive - same inhibitory mechanisms
        ('inhibitor', 'inhibitor'): 'additive',
        ('blocker', 'blocker'): 'additive',
        ('antagonist', 'inhibitor'): 'additive',
        
        # Synergistic - enhancing combinations
        ('agonist', 'pam'): 'synergistic',
        ('activator', 'activator'): 'synergistic',
        
        # Substrate interactions
        ('substrate', 'inhibitor'): 'enzyme_inhibition',
        ('substrate', 'substrate'): 'competitive_metabolism',
    }
    
    fixed_count = 0
    
    for interaction in unknown_interactions:
        # Get mechanisms for both compounds
        mechanisms_a = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_a,
            target=interaction.target
        ).first()
        
        mechanisms_b = CompoundTargetInteraction.objects.filter(
            compound=interaction.compound_b,
            target=interaction.target
        ).first()
        
        if mechanisms_a and mechanisms_b:
            mech_a = mechanisms_a.mechanism
            mech_b = mechanisms_b.mechanism
            
            # Apply interaction rules
            suggested_type = None
            
            # Check all rule combinations
            for (m1, m2), interaction_type in interaction_rules.items():
                if (mech_a == m1 and mech_b == m2) or (mech_a == m2 and mech_b == m1):
                    suggested_type = interaction_type
                    break
            
            if suggested_type:
                interaction.interaction_type = suggested_type
                interaction.description = f"{interaction.compound_a.name}: {mech_a}, {interaction.compound_b.name}: {mech_b}"
                interaction.save()
                fixed_count += 1
    
    print(f"✅ Fixed {fixed_count} compound-to-compound interactions!")
    
    return fixed_count

def main():
    print("Batch Unknown Interaction Fix Tool")
    print("=" * 40)
    
    response = input("Fix all unknown mechanisms and interactions? (yes/no): ").lower().strip()
    if response != 'yes':
        print("Cancelled.")
        return
    
    # Fix mechanisms first
    mechanism_count = batch_fix_mechanisms()
    
    # Then fix compound interactions
    interaction_count = batch_fix_interactions()
    
    print(f"\n🎉 Summary:")
    print(f"   Fixed {mechanism_count} unknown mechanisms")
    print(f"   Fixed {interaction_count} unknown compound interactions")
    print(f"   Total fixes: {mechanism_count + interaction_count}")

if __name__ == "__main__":
    main()
