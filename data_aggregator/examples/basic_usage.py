#!/usr/bin/env python3
"""
Example: Basic usage of ChemBio Importer
"""

import logging
from chembio_importer import db_manager, chembl_client, reactome_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Demonstrate basic usage of the ChemBio Importer"""
    
    # Initialize database
    print("Initializing database...")
    db_manager.create_tables()
    
    # Example 1: Get a specific compound from ChEMBL
    print("\n=== Example 1: Get specific compound ===")
    compound_data = chembl_client.get_compound_by_id("CHEMBL25")
    if compound_data:
        print(f"Compound: {compound_data['name']} ({compound_data['chembl_id']})")
        print(f"SMILES: {compound_data.get('canonical_smiles')}")
        print(f"Molecular Weight: {compound_data.get('molecular_weight')}")
    
    # Example 2: Get targets for a compound
    print("\n=== Example 2: Get compound targets ===")
    targets = chembl_client.get_compound_targets("CHEMBL25")
    print(f"Found {len(targets)} target interactions")
    for target in targets[:3]:  # Show first 3
        print(f"  - {target['target_chembl_id']}: {target.get('activity_type')} = {target.get('activity_value')} {target.get('activity_units')}")
    
    # Example 3: Get pathways for a protein
    print("\n=== Example 3: Get pathways for protein ===")
    pathways = reactome_client.get_pathways_for_identifier("P04637")  # TP53
    print(f"Found {len(pathways)} pathways for TP53")
    for pathway in pathways[:3]:  # Show first 3
        print(f"  - {pathway['stable_id']}: {pathway['name']}")
    
    # Example 4: Store data in database
    print("\n=== Example 4: Store data in database ===")
    with db_manager.get_session() as session:
        if compound_data:
            # Store compound
            compound, created = db_manager.get_or_create_compound(
                session, 
                chembl_id=compound_data['chembl_id'],
                name=compound_data['name'],
                canonical_smiles=compound_data.get('canonical_smiles'),
                molecular_weight=compound_data.get('molecular_weight')
            )
            
            print(f"Compound {'created' if created else 'updated'}: {compound.name}")
        
        # Get database statistics
        stats = db_manager.get_database_stats(session)
        print(f"\nDatabase contains:")
        for key, count in stats.items():
            print(f"  - {key}: {count}")

if __name__ == "__main__":
    main()
