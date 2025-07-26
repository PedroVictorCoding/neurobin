#!/usr/bin/env python3
"""
Example: Query and analyze the imported database
"""

import json
from collections import defaultdict, Counter
from chembio_importer import db_manager
from chembio_importer.models import Compound, Target, Pathway, CompoundTargetInteraction

def analyze_compound_targets():
    """Analyze compound-target interactions"""
    print("=== COMPOUND-TARGET ANALYSIS ===")
    
    with db_manager.get_session() as session:
        # Most common target types
        target_types = session.query(Target.target_type).all()
        type_counts = Counter([t[0] for t in target_types if t[0]])
        
        print("\nMost common target types:")
        for target_type, count in type_counts.most_common(10):
            print(f"  {target_type}: {count}")
        
        # Most common mechanisms
        mechanisms = session.query(CompoundTargetInteraction.mechanism).all()
        mechanism_counts = Counter([m[0] for m in mechanisms if m[0]])
        
        print("\nMost common mechanisms:")
        for mechanism, count in mechanism_counts.most_common(10):
            print(f"  {mechanism}: {count}")
        
        # Compounds with most targets
        compounds_with_target_counts = session.query(
            Compound.chembl_id, 
            Compound.name,
            session.query(CompoundTargetInteraction).filter(
                CompoundTargetInteraction.compound_id == Compound.id
            ).count().label('target_count')
        ).all()
        
        # Sort by target count
        sorted_compounds = sorted(compounds_with_target_counts, 
                                key=lambda x: x[2], reverse=True)
        
        print("\nCompounds with most targets:")
        for chembl_id, name, count in sorted_compounds[:10]:
            print(f"  {name} ({chembl_id}): {count} targets")

def analyze_pathways():
    """Analyze pathway data"""
    print("\n=== PATHWAY ANALYSIS ===")
    
    with db_manager.get_session() as session:
        # Pathway species distribution
        species = session.query(Pathway.species).all()
        species_counts = Counter([s[0] for s in species if s[0]])
        
        print("\nPathway species distribution:")
        for organism, count in species_counts.most_common(5):
            print(f"  {organism}: {count}")
        
        # Most connected pathways (by number of targets)
        pathways_with_target_counts = []
        pathways = session.query(Pathway).all()
        
        for pathway in pathways:
            target_count = len(pathway.targets)
            pathways_with_target_counts.append((pathway.name, pathway.stable_id, target_count))
        
        # Sort by target count
        sorted_pathways = sorted(pathways_with_target_counts, 
                               key=lambda x: x[2], reverse=True)
        
        print("\nMost connected pathways (by targets):")
        for name, stable_id, count in sorted_pathways[:10]:
            if count > 0:
                print(f"  {name} ({stable_id}): {count} targets")

def analyze_molecular_properties():
    """Analyze molecular properties of compounds"""
    print("\n=== MOLECULAR PROPERTIES ANALYSIS ===")
    
    with db_manager.get_session() as session:
        compounds = session.query(Compound).filter(
            Compound.molecular_weight.isnot(None)
        ).all()
        
        if not compounds:
            print("No compounds with molecular weight data found.")
            return
        
        # Calculate statistics
        molecular_weights = [c.molecular_weight for c in compounds if c.molecular_weight]
        logp_values = [c.logp for c in compounds if c.logp]
        
        if molecular_weights:
            print(f"\nMolecular Weight Statistics (n={len(molecular_weights)}):")
            print(f"  Mean: {sum(molecular_weights)/len(molecular_weights):.1f} Da")
            print(f"  Min: {min(molecular_weights):.1f} Da")
            print(f"  Max: {max(molecular_weights):.1f} Da")
        
        if logp_values:
            print(f"\nLogP Statistics (n={len(logp_values)}):")
            print(f"  Mean: {sum(logp_values)/len(logp_values):.2f}")
            print(f"  Min: {min(logp_values):.2f}")
            print(f"  Max: {max(logp_values):.2f}")
        
        # Drug-like compounds (Lipinski's Rule of Five)
        drug_like = 0
        for compound in compounds:
            if (compound.molecular_weight and compound.molecular_weight <= 500 and
                compound.logp and compound.logp <= 5 and
                compound.hbd and compound.hbd <= 5 and
                compound.hba and compound.hba <= 10):
                drug_like += 1
        
        print(f"\nDrug-like compounds (Lipinski's Rule of Five): {drug_like}/{len(compounds)} ({100*drug_like/len(compounds):.1f}%)")

def find_interesting_connections():
    """Find interesting compound-pathway connections"""
    print("\n=== INTERESTING CONNECTIONS ===")
    
    with db_manager.get_session() as session:
        # Find compounds that affect multiple neurotransmitter pathways
        neuro_keywords = ['serotonin', 'dopamine', 'GABA', 'acetylcholine', 'glutamate', 'norepinephrine']
        
        print("\nCompounds affecting neurotransmitter pathways:")
        compounds = session.query(Compound).all()
        
        for compound in compounds[:20]:  # Limit for demo
            neuro_pathways = []
            for pathway in compound.pathways:
                pathway_name_lower = pathway.name.lower()
                for keyword in neuro_keywords:
                    if keyword in pathway_name_lower:
                        neuro_pathways.append(pathway.name)
                        break
            
            if len(neuro_pathways) >= 2:
                print(f"  {compound.name} ({compound.chembl_id}):")
                for pathway_name in neuro_pathways[:3]:
                    print(f"    - {pathway_name}")

def export_summary():
    """Export a summary of the database"""
    print("\n=== EXPORTING SUMMARY ===")
    
    with db_manager.get_session() as session:
        stats = db_manager.get_database_stats(session)
        
        # Create summary data
        summary = {
            'database_stats': stats,
            'timestamp': db_manager.get_database_stats(session),
        }
        
        # Add sample data
        sample_compounds = []
        compounds = session.query(Compound).limit(5).all()
        for compound in compounds:
            sample_compounds.append({
                'chembl_id': compound.chembl_id,
                'name': compound.name,
                'molecular_weight': compound.molecular_weight,
                'target_count': len(compound.target_interactions),
                'pathway_count': len(compound.pathways)
            })
        
        summary['sample_compounds'] = sample_compounds
        
        # Save to file
        with open('database_summary.json', 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print("Summary exported to database_summary.json")

def main():
    """Run comprehensive database analysis"""
    print("CHEMBIO DATABASE ANALYSIS")
    print("=" * 50)
    
    # Check if database has data
    with db_manager.get_session() as session:
        stats = db_manager.get_database_stats(session)
        
        if stats['compounds'] == 0:
            print("No data found in database. Please run the importer first:")
            print("python -m chembio_importer --from-chembl --limit 100 --slow")
            return
        
        print(f"Database contains {stats['compounds']} compounds, {stats['targets']} targets, {stats['pathways']} pathways")
    
    # Run analyses
    analyze_compound_targets()
    analyze_pathways()
    analyze_molecular_properties()
    find_interesting_connections()
    export_summary()
    
    print("\nAnalysis complete!")

if __name__ == "__main__":
    main()
