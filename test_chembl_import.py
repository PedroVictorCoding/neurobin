#!/usr/bin/env python
"""
Test script to demonstrate ChEMBL compound interaction import functionality.
This creates sample compounds and shows how the import command would work.
"""

import os
import sys
import django

# Setup Django environment
sys.path.append('/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Compound, Target, CompoundTargetInteraction, CompoundToCompoundTargetInteraction

def create_sample_compounds():
    """Create sample compounds with ChEMBL IDs for testing."""
    compounds_data = [
        {
            'name': 'Caffeine',
            'chembl_id': 'CHEMBL25',
            'description': 'Central nervous system stimulant',
            'smiles': 'CN1C=NC2=C1C(=O)N(C(=O)N2C)C'
        },
        {
            'name': 'Fluoxetine',
            'chembl_id': 'CHEMBL154',
            'description': 'Selective serotonin reuptake inhibitor (SSRI)',
            'smiles': 'CNCCC(C1=CC=CC=C1)OC2=CC=C(C=C2)C(F)(F)F'
        },
        {
            'name': 'Modafinil',
            'chembl_id': 'CHEMBL1487',
            'description': 'Wakefulness-promoting agent',
            'smiles': 'NC(=O)C[S@](=O)C1=CC=C(C=C1)C(C)(C)C'
        },
        {
            'name': 'LSD',
            'chembl_id': 'CHEMBL112',
            'description': 'Psychedelic drug',
            'smiles': 'CCN(CC)C(=O)[C@H]1CN([C@@H]2CC3=CNC4=CC=CC(=C34)C2=C1)C'
        },
        {
            'name': 'Ketamine',
            'chembl_id': 'CHEMBL122',
            'description': 'NMDA receptor antagonist',
            'smiles': 'CNC1(CCCCC1=O)C2=CC=CC=C2Cl'
        }
    ]
    
    created_compounds = []
    for data in compounds_data:
        compound, created = Compound.objects.get_or_create(
            name=data['name'],
            defaults={
                'chembl_id': data['chembl_id'],
                'description': data['description'],
                'smiles': data['smiles']
            }
        )
        if created:
            print(f"[✓] Created compound: {compound.name} ({compound.chembl_id})")
        else:
            print(f"[i] Compound already exists: {compound.name}")
        created_compounds.append(compound)
    
    return created_compounds

def create_sample_targets():
    """Create sample targets for testing."""
    targets_data = [
        {
            'name': 'Serotonin transporter',
            'chembl_id': 'CHEMBL228',
            'target_type': 'transporter',
            'description': 'Sodium-dependent serotonin transporter',
            'organism': 'Homo sapiens'
        },
        {
            'name': 'Dopamine D2 receptor',
            'chembl_id': 'CHEMBL217',
            'target_type': 'receptor',
            'description': 'D(2) dopamine receptor',
            'organism': 'Homo sapiens'
        },
        {
            'name': 'NMDA receptor',
            'chembl_id': 'CHEMBL4792',
            'target_type': 'ion_channel',
            'description': 'N-methyl-D-aspartate receptor',
            'organism': 'Homo sapiens'
        },
        {
            'name': 'Adenosine A2A receptor',
            'chembl_id': 'CHEMBL251',
            'target_type': 'receptor',
            'description': 'Adenosine receptor A2a',
            'organism': 'Homo sapiens'
        }
    ]
    
    created_targets = []
    for data in targets_data:
        target, created = Target.objects.get_or_create(
            name=data['name'],
            defaults={
                'chembl_id': data['chembl_id'],
                'target_type': data['target_type'],
                'description': data['description'],
                'organism': data['organism']
            }
        )
        if created:
            print(f"[✓] Created target: {target.name} ({target.chembl_id})")
        else:
            print(f"[i] Target already exists: {target.name}")
        created_targets.append(target)
    
    return created_targets

def create_sample_interactions(compounds, targets):
    """Create sample compound-target interactions."""
    interactions_data = [
        # Caffeine interactions
        {
            'compound_name': 'Caffeine',
            'target_name': 'Adenosine A2A receptor',
            'mechanism': 'antagonist',
            'affinity_level': 'high',
            'notes': 'Caffeine blocks adenosine receptors'
        },
        # Fluoxetine interactions
        {
            'compound_name': 'Fluoxetine',
            'target_name': 'Serotonin transporter',
            'mechanism': 'inhibitor',
            'affinity_level': 'high',
            'notes': 'SSRI - blocks serotonin reuptake'
        },
        # Ketamine interactions
        {
            'compound_name': 'Ketamine',
            'target_name': 'NMDA receptor',
            'mechanism': 'antagonist',
            'affinity_level': 'medium',
            'notes': 'Non-competitive NMDA antagonist'
        },
        # LSD interactions
        {
            'compound_name': 'LSD',
            'target_name': 'Serotonin transporter',
            'mechanism': 'agonist',
            'affinity_level': 'high',
            'notes': 'Psychedelic effects via serotonin system'
        }
    ]
    
    compound_map = {c.name: c for c in compounds}
    target_map = {t.name: t for t in targets}
    
    created_interactions = []
    for data in interactions_data:
        compound = compound_map.get(data['compound_name'])
        target = target_map.get(data['target_name'])
        
        if compound and target:
            interaction, created = CompoundTargetInteraction.objects.get_or_create(
                compound=compound,
                target=target,
                mechanism=data['mechanism'],
                defaults={
                    'affinity_level': data['affinity_level'],
                    'notes': data['notes'],
                    'source': 'manual_test'
                }
            )
            if created:
                print(f"[✓] Created interaction: {compound.name} → {target.name} ({data['mechanism']})")
                created_interactions.append(interaction)
            else:
                print(f"[i] Interaction already exists: {compound.name} → {target.name}")
    
    return created_interactions

def create_compound_compound_interactions():
    """Create compound-to-compound interactions based on shared targets."""
    shared_targets = Target.objects.filter(
        compound_interactions__isnull=False
    ).distinct()
    
    created_count = 0
    
    for target in shared_targets:
        # Get compounds that interact with this target
        interactions = CompoundTargetInteraction.objects.filter(target=target)
        compounds = [interaction.compound for interaction in interactions]
        
        # Create pairs
        for i in range(len(compounds)):
            for j in range(i + 1, len(compounds)):
                compound_a = compounds[i]
                compound_b = compounds[j]
                
                # Get mechanisms
                mechanism_a = interactions.filter(compound=compound_a).first().mechanism
                mechanism_b = interactions.filter(compound=compound_b).first().mechanism
                
                # Infer interaction type
                if mechanism_a == mechanism_b:
                    interaction_type = 'synergistic'
                elif (mechanism_a == 'agonist' and mechanism_b == 'antagonist') or \
                     (mechanism_a == 'antagonist' and mechanism_b == 'agonist'):
                    interaction_type = 'antagonistic'
                else:
                    interaction_type = 'competitive'
                
                # Create interaction
                interaction, created = CompoundToCompoundTargetInteraction.objects.get_or_create(
                    compound_a=compound_a,
                    compound_b=compound_b,
                    target=target,
                    defaults={
                        'interaction_type': interaction_type,
                        'description': f"{compound_a.name}: {mechanism_a}, {compound_b.name}: {mechanism_b}",
                        'confidence': 'medium',
                        'source': 'test_data'
                    }
                )
                
                if created:
                    print(f"[✓] Created compound interaction: {compound_a.name} ↔ {compound_b.name} via {target.name}")
                    created_count += 1
    
    return created_count

def main():
    """Main function to demonstrate ChEMBL import functionality."""
    print("=== ChEMBL Import Demonstration ===")
    print()
    
    print("1. Creating sample compounds...")
    compounds = create_sample_compounds()
    print()
    
    print("2. Creating sample targets...")
    targets = create_sample_targets()
    print()
    
    print("3. Creating compound-target interactions...")
    interactions = create_sample_interactions(compounds, targets)
    print()
    
    print("4. Creating compound-to-compound interactions...")
    compound_interactions = create_compound_compound_interactions()
    print()
    
    print("=== Summary ===")
    print(f"Compounds: {Compound.objects.count()}")
    print(f"Targets: {Target.objects.count()}")
    print(f"Compound-Target Interactions: {CompoundTargetInteraction.objects.count()}")
    print(f"Compound-Compound Interactions: {CompoundToCompoundTargetInteraction.objects.count()}")
    print()
    
    print("=== Usage Examples ===")
    print()
    
    print("To run the actual ChEMBL import command:")
    print("python manage.py import_chembl_interactions --compounds=CHEMBL25,CHEMBL154")
    print()
    
    print("To import all compounds with ChEMBL IDs:")
    print("python manage.py import_chembl_interactions --all-compounds")
    print()
    
    print("To import from a file:")
    print("python manage.py import_chembl_interactions --file=compound_ids.txt")
    print()
    
    print("Note: The import command requires the 'requests' library.")
    print("Install with: pip install requests")

if __name__ == '__main__':
    main()
