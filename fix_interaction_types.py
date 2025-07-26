#!/usr/bin/env python
"""
Fix interaction types based on proper pharmacological classification.

This script corrects the interaction types by implementing the rules:
- SYNERGISTIC: Different mechanisms with same functional outcome (e.g., PAM + Agonist)
- ADDITIVE: Same mechanisms (e.g., inhibitor + inhibitor) 
- ANTAGONISTIC: Opposing mechanisms/outcomes (e.g., agonist + antagonist)
- COMPETITIVE: Same binding site/mechanism type but different compounds
"""

import os
import sys
import django

# Add the project root to Python path
sys.path.insert(0, '/home/main/Dev/neurobin/core')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import CompoundToCompoundTargetInteraction, CompoundTargetInteraction
from django.db.models import Count


def classify_interaction_type(mechanism1: str, mechanism2: str) -> str:
    """
    Classify interaction type based on mechanisms using pharmacologically accurate rules.
    """
    
    # Define mechanism functional outcomes
    activating_mechanisms = {'agonist', 'activator', 'opener', 'inducer', 'pam'}
    inhibiting_mechanisms = {'antagonist', 'inhibitor', 'blocker', 'nam'}
    modulatory_mechanisms = {'modulator'}  # Could be either direction
    metabolic_mechanisms = {'substrate'}
    binding_mechanisms = {'binder'}
    
    # Both mechanisms are exactly the same - ADDITIVE
    if mechanism1 == mechanism2:
        if mechanism1 in activating_mechanisms or mechanism1 in inhibiting_mechanisms:
            return 'additive'
        elif mechanism1 in modulatory_mechanisms:
            return 'additive'  # Same type modulators are additive
        elif mechanism1 in metabolic_mechanisms:
            return 'competitive_metabolism'
        elif mechanism1 in binding_mechanisms:
            return 'competitive'
        else:
            return 'additive'
    
    # Different mechanisms with SAME functional outcome - SYNERGISTIC
    mech1_activating = mechanism1 in activating_mechanisms
    mech2_activating = mechanism2 in activating_mechanisms
    mech1_inhibiting = mechanism1 in inhibiting_mechanisms
    mech2_inhibiting = mechanism2 in inhibiting_mechanisms
    
    if (mech1_activating and mech2_activating) or (mech1_inhibiting and mech2_inhibiting):
        # Different mechanisms but same outcome - synergistic
        if mechanism1 != mechanism2:
            return 'synergistic'
    
    # Opposing mechanisms - ANTAGONISTIC
    if (mech1_activating and mech2_inhibiting) or (mech1_inhibiting and mech2_activating):
        return 'antagonistic'
    
    # Substrate + Inhibitor interactions - special case
    if (mechanism1 == 'substrate' and mechanism2 in inhibiting_mechanisms) or \
       (mechanism2 == 'substrate' and mechanism1 in inhibiting_mechanisms):
        return 'enzyme_inhibition'
    
    # Both substrates - metabolic competition
    if mechanism1 == 'substrate' and mechanism2 == 'substrate':
        return 'competitive_metabolism'
    
    # One is modulator, other has clear direction
    if mechanism1 in modulatory_mechanisms or mechanism2 in modulatory_mechanisms:
        non_mod = mechanism2 if mechanism1 in modulatory_mechanisms else mechanism1
        if non_mod in activating_mechanisms or non_mod in inhibiting_mechanisms:
            return 'synergistic'  # Modulators typically enhance other mechanisms
    
    # Both are binding without clear functional effect
    if mechanism1 in binding_mechanisms or mechanism2 in binding_mechanisms:
        return 'competitive'
    
    # Default for unclear combinations
    if mechanism1 != 'unknown' and mechanism2 != 'unknown':
        return 'competitive'
    
    return 'unknown'


def main():
    print("🔬 Fixing Compound Interaction Types")
    print("=" * 50)
    
    # Get current distribution
    print("\n📊 Current interaction type distribution:")
    current_types = CompoundToCompoundTargetInteraction.objects.values('interaction_type').annotate(count=Count('id')).order_by('-count')
    for t in current_types:
        print(f"  {t['interaction_type']}: {t['count']}")
    
    total_interactions = CompoundToCompoundTargetInteraction.objects.count()
    print(f"\nTotal interactions: {total_interactions}")
    
    if total_interactions == 0:
        print("❌ No interactions found in database!")
        return
    
    # Fix interactions in batches
    print("\n🔧 Fixing interaction types in batches...")
    fixed_count = 0
    error_count = 0
    batch_size = 1000
    
    # Only process interactions that currently have 'synergistic' type from the old incorrect logic
    incorrect_interactions = CompoundToCompoundTargetInteraction.objects.filter(
        interaction_type__in=['synergistic', 'unknown']
    ).select_related('compound_a', 'compound_b', 'target')
    
    total_to_fix = incorrect_interactions.count()
    print(f"Found {total_to_fix} interactions to potentially fix")
    
    for i in range(0, total_to_fix, batch_size):
        print(f"Processing batch {i//batch_size + 1}...")
        batch = incorrect_interactions[i:i+batch_size]
        
        for interaction in batch:
            try:
                # Get mechanisms for both compounds using select_related for efficiency
                mechanism_a = None
                mechanism_b = None
                
                # Find mechanisms for compound A
                try:
                    interaction_a = CompoundTargetInteraction.objects.select_related('compound', 'target').get(
                        compound=interaction.compound_a,
                        target=interaction.target
                    )
                    mechanism_a = interaction_a.mechanism
                except CompoundTargetInteraction.DoesNotExist:
                    pass
                
                # Find mechanisms for compound B  
                try:
                    interaction_b = CompoundTargetInteraction.objects.select_related('compound', 'target').get(
                        compound=interaction.compound_b,
                        target=interaction.target
                    )
                    mechanism_b = interaction_b.mechanism
                except CompoundTargetInteraction.DoesNotExist:
                    pass
                
                if not mechanism_a or not mechanism_b:
                    error_count += 1
                    continue
                
                # Calculate new interaction type
                old_type = interaction.interaction_type
                new_type = classify_interaction_type(mechanism_a, mechanism_b)
                
                if old_type != new_type:
                    interaction.interaction_type = new_type
                    interaction.description = f"{interaction.compound_a.name}: {mechanism_a}, {interaction.compound_b.name}: {mechanism_b}"
                    interaction.save()
                    fixed_count += 1
                    
                    if fixed_count % 100 == 0:
                        print(f"  Fixed {fixed_count} interactions...")
                
            except Exception as e:
                print(f"❌ Error processing interaction {interaction.id}: {e}")
                error_count += 1
    
    print(f"\n📈 Summary:")
    print(f"  Fixed: {fixed_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total processed: {fixed_count + error_count}")
    
    # Show new distribution
    print("\n📊 New interaction type distribution:")
    new_types = CompoundToCompoundTargetInteraction.objects.values('interaction_type').annotate(count=Count('id')).order_by('-count')
    for t in new_types:
        print(f"  {t['interaction_type']}: {t['count']}")
    
    print("\n✅ Done! Interaction types have been corrected using proper pharmacological principles.")
    print("Key changes:")
    print("  - Same mechanisms (inhibitor+inhibitor) → additive")
    print("  - Different mechanisms, same outcome (PAM+agonist) → synergistic")
    print("  - Opposing mechanisms (agonist+antagonist) → antagonistic")


if __name__ == "__main__":
    main()
