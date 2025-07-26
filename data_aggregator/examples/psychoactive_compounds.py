#!/usr/bin/env python3
"""
Example: Import specific psychoactive compounds and analyze their effects
"""

import logging
from chembio_importer import db_manager
from chembio_importer.__main__ import ChemBioImporter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# List of interesting psychoactive compounds
PSYCHOACTIVE_COMPOUNDS = [
    "CHEMBL59",     # LSD
    "CHEMBL6129",   # Psilocybin  
    "CHEMBL1628",   # Mescaline
    "CHEMBL25",     # Morphine
    "CHEMBL113",    # Cocaine
    "CHEMBL1201585", # THC
    "CHEMBL637",    # Fluoxetine (Prozac)
    "CHEMBL809",    # Diazepam (Valium)
    "CHEMBL11",     # Caffeine
]

def main():
    """Import and analyze psychoactive compounds"""
    
    # Initialize importer
    importer = ChemBioImporter()
    importer.initialize_database()
    
    print("Importing psychoactive compounds...")
    
    # Import each compound
    for chembl_id in PSYCHOACTIVE_COMPOUNDS:
        print(f"\nImporting {chembl_id}...")
        try:
            importer.import_from_chembl(specific_compound=chembl_id)
            print(f"✓ Successfully imported {chembl_id}")
        except Exception as e:
            print(f"✗ Failed to import {chembl_id}: {e}")
    
    # Import relevant pathways
    print("\nImporting pathways for targets...")
    importer.import_pathways_from_reactome(targets_only=True)
    
    # Analyze the data
    print("\n" + "="*50)
    print("ANALYSIS OF PSYCHOACTIVE COMPOUNDS")
    print("="*50)
    
    with db_manager.get_session() as session:
        from chembio_importer.models import Compound, Target, CompoundTargetInteraction
        
        # Get all imported compounds
        compounds = session.query(Compound).filter(
            Compound.chembl_id.in_(PSYCHOACTIVE_COMPOUNDS)
        ).all()
        
        print(f"\nSuccessfully imported {len(compounds)} compounds:")
        
        for compound in compounds:
            print(f"\n{compound.name} ({compound.chembl_id})")
            print(f"  MW: {compound.molecular_weight:.1f} Da" if compound.molecular_weight else "  MW: Unknown")
            print(f"  LogP: {compound.logp:.2f}" if compound.logp else "  LogP: Unknown")
            print(f"  Approval Status: {compound.approval_status}")
            
            # Show targets
            interactions = session.query(CompoundTargetInteraction).filter(
                CompoundTargetInteraction.compound_id == compound.id
            ).all()
            
            if interactions:
                print(f"  Targets ({len(interactions)}):")
                for interaction in interactions[:5]:  # Show top 5
                    target = interaction.target
                    activity = f"{interaction.activity_value:.1f} {interaction.activity_units}" if interaction.activity_value else "N/A"
                    print(f"    - {target.gene_symbol or target.name}: {interaction.mechanism} ({activity})")
            
            # Show pathways
            if compound.pathways:
                print(f"  Pathways ({len(compound.pathways)}):")
                for pathway in compound.pathways[:3]:  # Show top 3
                    print(f"    - {pathway.name}")
            
            # Show effect profile
            if compound.effect_profile:
                print(f"  Effect Profile: {compound.effect_profile}")
        
        # Summary statistics
        stats = db_manager.get_database_stats(session)
        print(f"\n" + "-"*50)
        print("DATABASE SUMMARY:")
        print(f"  Total compounds: {stats['compounds']}")
        print(f"  Total targets: {stats['targets']}")
        print(f"  Total pathways: {stats['pathways']}")
        print(f"  Total interactions: {stats['interactions']}")

if __name__ == "__main__":
    main()
