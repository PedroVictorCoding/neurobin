#!/usr/bin/env python
"""
Fix interactions by updating mechanism data from ChEMBL API for compounds with 'unknown' mechanisms.
"""

import os
import sys
import django

# Add the project root to Python path
sys.path.insert(0, '/home/main/Dev/neurobin/core')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import CompoundToCompoundTargetInteraction, CompoundTargetInteraction, Compound
from compounds.management.commands.import_chembl_interactions import ChEMBLImporter
from django.db.models import Q


def fix_unknown_mechanisms():
    """Fix interactions that have unknown mechanisms by re-checking ChEMBL data."""
    
    print("🔧 Fixing Unknown Mechanism Interactions")
    print("=" * 50)
    
    # Find interactions where one or both compounds have 'unknown' mechanism
    unknown_interactions = CompoundToCompoundTargetInteraction.objects.filter(
        Q(interaction_type='unknown') |
        Q(description__icontains='unknown')
    ).select_related('compound_a', 'compound_b', 'target')[:200]  # Start with smaller batch
    
    print(f"Found {unknown_interactions.count()} interactions with unknown mechanisms")
    
    importer = ChEMBLImporter(slow_mode=True)  # Use slow mode to be polite to ChEMBL API
    fixed_count = 0
    
    for i, interaction in enumerate(unknown_interactions):
        print(f"\n[{i+1}/{unknown_interactions.count()}] Checking: {interaction.compound_a.name} ↔ {interaction.compound_b.name}")
        
        try:
            # Check if compounds have ChEMBL IDs
            compound_a_chembl = interaction.compound_a.chembl_id
            compound_b_chembl = interaction.compound_b.chembl_id
            
            mechanisms_updated = False
            
            # Update mechanism for compound A if it has ChEMBL ID and currently unknown
            current_interaction_a = CompoundTargetInteraction.objects.filter(
                compound=interaction.compound_a,
                target=interaction.target
            ).first()
            
            if (current_interaction_a and current_interaction_a.mechanism == 'unknown' and 
                compound_a_chembl and compound_a_chembl.startswith('CHEMBL')):
                
                print(f"  Updating {interaction.compound_a.name} mechanism from ChEMBL...")
                
                # Get fresh mechanism data from ChEMBL
                mechanisms = importer.get_compound_mechanisms(compound_a_chembl)
                
                # Find mechanism for this specific target
                for mech_data in mechanisms:
                    if mech_data.get('target_chembl_id') == interaction.target.chembl_id:
                        mechanism_raw = mech_data.get('mechanism_of_action', '')
                        new_mechanism = importer.normalize_mechanism(mechanism_raw)
                        
                        if new_mechanism != 'unknown':
                            current_interaction_a.mechanism = new_mechanism
                            current_interaction_a.save()
                            print(f"    → Updated to: {new_mechanism}")
                            mechanisms_updated = True
                            break
            
            # Update mechanism for compound B if it has ChEMBL ID and currently unknown
            current_interaction_b = CompoundTargetInteraction.objects.filter(
                compound=interaction.compound_b,
                target=interaction.target
            ).first()
            
            if (current_interaction_b and current_interaction_b.mechanism == 'unknown' and 
                compound_b_chembl and compound_b_chembl.startswith('CHEMBL')):
                
                print(f"  Updating {interaction.compound_b.name} mechanism from ChEMBL...")
                
                # Get fresh mechanism data from ChEMBL
                mechanisms = importer.get_compound_mechanisms(compound_b_chembl)
                
                # Find mechanism for this specific target
                for mech_data in mechanisms:
                    if mech_data.get('target_chembl_id') == interaction.target.chembl_id:
                        mechanism_raw = mech_data.get('mechanism_of_action', '')
                        new_mechanism = importer.normalize_mechanism(mechanism_raw)
                        
                        if new_mechanism != 'unknown':
                            current_interaction_b.mechanism = new_mechanism
                            current_interaction_b.save()
                            print(f"    → Updated to: {new_mechanism}")
                            mechanisms_updated = True
                            break
            
            # If we updated mechanisms, recalculate interaction type
            if mechanisms_updated:
                # Re-fetch the interactions
                updated_interaction_a = CompoundTargetInteraction.objects.get(
                    compound=interaction.compound_a,
                    target=interaction.target
                )
                updated_interaction_b = CompoundTargetInteraction.objects.get(
                    compound=interaction.compound_b,
                    target=interaction.target
                )
                
                mechanism_a = updated_interaction_a.mechanism
                mechanism_b = updated_interaction_b.mechanism
                
                if mechanism_a != 'unknown' and mechanism_b != 'unknown':
                    # Use the improved classification logic
                    new_interaction_type = classify_interaction_type(mechanism_a, mechanism_b)
                    
                    interaction.interaction_type = new_interaction_type
                    interaction.description = f"{interaction.compound_a.name}: {mechanism_a}, {interaction.compound_b.name}: {mechanism_b}"
                    interaction.save()
                    
                    print(f"  ✅ Updated interaction type: {new_interaction_type}")
                    fixed_count += 1
                else:
                    print(f"  ⚠️  Still has unknown mechanisms: {mechanism_a}, {mechanism_b}")
            else:
                print(f"  ℹ️  No ChEMBL data available or already has known mechanisms")
        
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        # Add delay to be polite to ChEMBL API
        if i < unknown_interactions.count() - 1:
            import time
            time.sleep(2)  # 2 second delay between compounds
    
    print(f"\n📊 Summary:")
    print(f"  Fixed interactions: {fixed_count}")
    print(f"  Processed: {unknown_interactions.count()}")


def classify_interaction_type(mechanism1: str, mechanism2: str) -> str:
    """Classify interaction type based on mechanisms using pharmacologically accurate rules."""
    
    # Define mechanism functional outcomes
    activating_mechanisms = {'agonist', 'activator', 'opener', 'inducer', 'pam'}
    inhibiting_mechanisms = {'antagonist', 'inhibitor', 'blocker', 'nam'}
    modulatory_mechanisms = {'modulator'}
    metabolic_mechanisms = {'substrate'}
    binding_mechanisms = {'binder'}
    
    # Both mechanisms are exactly the same - ADDITIVE
    if mechanism1 == mechanism2:
        if mechanism1 in activating_mechanisms or mechanism1 in inhibiting_mechanisms:
            return 'additive'
        elif mechanism1 in modulatory_mechanisms:
            return 'additive'
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
        if mechanism1 != mechanism2:
            return 'synergistic'
    
    # Opposing mechanisms - ANTAGONISTIC
    if (mech1_activating and mech2_inhibiting) or (mech1_inhibiting and mech2_activating):
        return 'antagonistic'
    
    # Special cases
    if (mechanism1 == 'substrate' and mechanism2 in inhibiting_mechanisms) or \
       (mechanism2 == 'substrate' and mechanism1 in inhibiting_mechanisms):
        return 'enzyme_inhibition'
    
    if mechanism1 == 'substrate' and mechanism2 == 'substrate':
        return 'competitive_metabolism'
    
    # Modulator interactions
    if mechanism1 in modulatory_mechanisms or mechanism2 in modulatory_mechanisms:
        non_mod = mechanism2 if mechanism1 in modulatory_mechanisms else mechanism1
        if non_mod in activating_mechanisms or non_mod in inhibiting_mechanisms:
            return 'synergistic'
    
    # Binding interactions
    if mechanism1 in binding_mechanisms or mechanism2 in binding_mechanisms:
        return 'competitive'
    
    # Default
    if mechanism1 != 'unknown' and mechanism2 != 'unknown':
        return 'competitive'
    
    return 'unknown'


if __name__ == "__main__":
    fix_unknown_mechanisms()
