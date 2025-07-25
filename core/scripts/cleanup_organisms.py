#!/usr/bin/env python
"""
Script to clean up organisms in the Neurobin database
- Remove all organisms that aren't Homo sapiens
- Remove compound mechanisms for blacklisted organisms
"""

import os
import sys
import django
from django.db import connection, transaction

# Setup Django
sys.path.insert(0, '/home/main/Dev/neurobin/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import Target, CompoundMechanismOfAction, CompoundTargetInteraction

def show_current_organisms():
    """Show current organism distribution"""
    print("=== Current Organism Distribution ===")
    
    # Get organism counts from targets
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT organism, COUNT(*) as count 
            FROM compounds_target 
            WHERE organism != '' 
            GROUP BY organism 
            ORDER BY count DESC
        """)
        
        print("Targets by organism:")
        for row in cursor.fetchall():
            print(f"  {row[0]}: {row[1]} targets")
    
    total_targets = Target.objects.count()
    total_mechanisms = CompoundMechanismOfAction.objects.count()
    total_interactions = CompoundTargetInteraction.objects.count()
    
    print(f"\nTotal targets: {total_targets}")
    print(f"Total mechanisms: {total_mechanisms}")
    print(f"Total target interactions: {total_interactions}")

def clean_non_homo_sapiens_organisms():
    """Remove all targets that are not Homo sapiens"""
    print("\n=== Removing Non-Homo sapiens Organisms ===")
    
    with transaction.atomic():
        # Get targets to be removed
        targets_to_remove = Target.objects.exclude(organism='').exclude(organism='Homo sapiens')
        
        print(f"Targets to be removed: {targets_to_remove.count()}")
        
        for organism in targets_to_remove.values('organism').distinct():
            count = targets_to_remove.filter(organism=organism['organism']).count()
            print(f"  {organism['organism']}: {count} targets")
        
        # Remove the targets (this will cascade to interactions)
        deleted_count = targets_to_remove.delete()
        print(f"Deleted: {deleted_count}")

def clean_blacklisted_mechanisms():
    """Remove compound mechanisms for blacklisted organisms"""
    print("\n=== Removing Blacklisted Mechanism Organisms ===")
    
    blacklisted_organisms = [
        'Mus musculus',
        'Rattus norvegicus', 
        'Homo sapiens',
        'Cavia porcellus',
        'Oryctolagus cuniculus'
    ]
    
    with transaction.atomic():
        # Find mechanisms that reference targets from blacklisted organisms
        mechanisms_to_remove = CompoundMechanismOfAction.objects.filter(
            target_name__organism__in=blacklisted_organisms
        )
        
        print(f"Mechanisms to be removed: {mechanisms_to_remove.count()}")
        
        # Group by target organism for reporting
        for organism in blacklisted_organisms:
            count = mechanisms_to_remove.filter(target_name__organism=organism).count()
            if count > 0:
                print(f"  {organism}: {count} mechanisms")
        
        # Remove the mechanisms
        deleted_count = mechanisms_to_remove.delete()
        print(f"Deleted: {deleted_count}")

def verify_cleanup():
    """Verify the cleanup results"""
    print("\n=== Verification After Cleanup ===")
    show_current_organisms()

def main():
    print("Neurobin Database Organism Cleanup")
    print("=" * 50)
    
    # Show initial state
    show_current_organisms()
    
    # Confirm before proceeding
    response = input("\nProceed with cleanup? (yes/no): ").lower().strip()
    if response != 'yes':
        print("Cleanup cancelled.")
        return
    
    try:
        # Step 1: Clean non-Homo sapiens organisms
        clean_non_homo_sapiens_organisms()
        
        # Step 2: Clean blacklisted mechanisms  
        clean_blacklisted_mechanisms()
        
        # Step 3: Verify results
        verify_cleanup()
        
        print("\n✅ Cleanup completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error during cleanup: {e}")
        print("All changes have been rolled back.")
        raise

if __name__ == "__main__":
    main()
