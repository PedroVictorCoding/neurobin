#!/usr/bin/env python
"""
Script to remove all targets with non-human organisms from the database
This script will:
1. Show current organism distribution
2. Remove all targets that don't have 'Homo sapiens' as organism
3. Clean up orphaned interactions and mechanisms
4. Show final statistics
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
            SELECT 
                CASE 
                    WHEN organism = '' OR organism IS NULL THEN '[Empty/NULL]'
                    ELSE organism 
                END as organism_display,
                COUNT(*) as count 
            FROM compounds_target 
            GROUP BY organism 
            ORDER BY count DESC
        """)
        
        print("Targets by organism:")
        total_targets = 0
        homo_sapiens_count = 0
        for row in cursor.fetchall():
            organism_display, count = row
            total_targets += count
            if organism_display == 'Homo sapiens':
                homo_sapiens_count = count
            print(f"  {organism_display}: {count} targets")
        
        print(f"\nTotal targets: {total_targets}")
        print(f"Homo sapiens targets: {homo_sapiens_count}")
        print(f"Non-human targets: {total_targets - homo_sapiens_count}")
    
    # Get related data counts
    total_mechanisms = CompoundMechanismOfAction.objects.count()
    total_interactions = CompoundTargetInteraction.objects.count()
    
    print(f"Total mechanisms: {total_mechanisms}")
    print(f"Total target interactions: {total_interactions}")

def remove_non_human_targets():
    """Remove all targets that are not Homo sapiens"""
    print("\n=== Removing Non-Human Targets ===")
    
    # First, identify non-human targets
    non_human_targets = Target.objects.exclude(organism='Homo sapiens').exclude(organism='')
    empty_organism_targets = Target.objects.filter(organism='')
    
    print(f"Found {non_human_targets.count()} targets with non-human organisms")
    print(f"Found {empty_organism_targets.count()} targets with empty organism")
    
    if non_human_targets.count() == 0:
        print("No non-human targets to remove!")
        return
    
    # Show which organisms will be removed
    print("\nNon-human organisms to be removed:")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT organism, COUNT(*) as count 
            FROM compounds_target 
            WHERE organism != 'Homo sapiens' AND organism != ''
            GROUP BY organism 
            ORDER BY count DESC
        """)
        
        for row in cursor.fetchall():
            organism, count = row
            print(f"  {organism}: {count} targets")
    
    # Ask for confirmation
    print(f"\nThis will remove {non_human_targets.count()} targets and their associated interactions.")
    
    if input("Are you sure you want to proceed? (y/N): ").lower() != 'y':
        print("Operation cancelled.")
        return
    
    with transaction.atomic():
        # Count related objects before deletion
        target_ids = list(non_human_targets.values_list('id', flat=True))
        
        # Find related interactions that will be deleted
        interactions_to_delete = CompoundTargetInteraction.objects.filter(target_id__in=target_ids)
        interactions_count = interactions_to_delete.count()
        
        # Find related mechanisms that reference these targets
        mechanisms_to_update = CompoundMechanismOfAction.objects.filter(target_name_id__in=target_ids)
        mechanisms_count = mechanisms_to_update.count()
        
        print(f"Will delete {interactions_count} compound-target interactions")
        print(f"Will update {mechanisms_count} compound mechanisms (remove target reference)")
        
        # Delete compound-target interactions first
        if interactions_count > 0:
            deleted_interactions = interactions_to_delete.delete()
            print(f"✓ Deleted {deleted_interactions[0]} compound-target interactions")
        
        # Update mechanisms to remove target references (don't delete the mechanisms)
        if mechanisms_count > 0:
            updated_mechanisms = mechanisms_to_update.update(target_name=None)
            print(f"✓ Updated {updated_mechanisms} compound mechanisms (removed target references)")
        
        # Delete the non-human targets
        deleted_targets = non_human_targets.delete()
        print(f"✓ Deleted {deleted_targets[0]} non-human targets")
        
        print("\n✓ Non-human target cleanup completed successfully!")

def remove_empty_organism_targets():
    """Optionally remove targets with empty organism field"""
    print("\n=== Empty Organism Targets ===")
    
    empty_targets = Target.objects.filter(organism='')
    count = empty_targets.count()
    
    if count == 0:
        print("No targets with empty organism field found.")
        return
    
    print(f"Found {count} targets with empty organism field")
    
    # Show some examples
    print("\nExamples of targets with empty organism:")
    for target in empty_targets[:10]:
        print(f"  - {target.name} (ChEMBL: {target.chembl_id or 'N/A'})")
    
    if count > 10:
        print(f"  ... and {count - 10} more")
    
    print(f"\nDo you want to remove targets with empty organism field?")
    print("Note: These might be valid human targets that just lack organism annotation.")
    
    if input("Remove empty organism targets? (y/N): ").lower() == 'y':
        with transaction.atomic():
            # Count related objects
            target_ids = list(empty_targets.values_list('id', flat=True))
            
            interactions_to_delete = CompoundTargetInteraction.objects.filter(target_id__in=target_ids)
            interactions_count = interactions_to_delete.count()
            
            mechanisms_to_update = CompoundMechanismOfAction.objects.filter(target_name_id__in=target_ids)
            mechanisms_count = mechanisms_to_update.count()
            
            print(f"Will delete {interactions_count} compound-target interactions")
            print(f"Will update {mechanisms_count} compound mechanisms")
            
            # Delete interactions
            if interactions_count > 0:
                deleted_interactions = interactions_to_delete.delete()
                print(f"✓ Deleted {deleted_interactions[0]} interactions")
            
            # Update mechanisms
            if mechanisms_count > 0:
                updated_mechanisms = mechanisms_to_update.update(target_name=None)
                print(f"✓ Updated {updated_mechanisms} mechanisms")
            
            # Delete targets
            deleted_targets = empty_targets.delete()
            print(f"✓ Deleted {deleted_targets[0]} empty organism targets")
    else:
        print("Keeping targets with empty organism field.")

def show_final_stats():
    """Show final statistics after cleanup"""
    print("\n=== Final Statistics ===")
    
    total_targets = Target.objects.count()
    homo_sapiens_targets = Target.objects.filter(organism='Homo sapiens').count()
    empty_organism_targets = Target.objects.filter(organism='').count()
    
    print(f"Total targets remaining: {total_targets}")
    print(f"Homo sapiens targets: {homo_sapiens_targets}")
    print(f"Empty organism targets: {empty_organism_targets}")
    print(f"Other organism targets: {total_targets - homo_sapiens_targets - empty_organism_targets}")
    
    total_mechanisms = CompoundMechanismOfAction.objects.count()
    total_interactions = CompoundTargetInteraction.objects.count()
    
    print(f"Total mechanisms: {total_mechanisms}")
    print(f"Total target interactions: {total_interactions}")
    
    # Show remaining organisms
    print("\nRemaining organisms:")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN organism = '' OR organism IS NULL THEN '[Empty/NULL]'
                    ELSE organism 
                END as organism_display,
                COUNT(*) as count 
            FROM compounds_target 
            GROUP BY organism 
            ORDER BY count DESC
        """)
        
        for row in cursor.fetchall():
            organism_display, count = row
            print(f"  {organism_display}: {count} targets")

def main():
    print("🧬 Non-Human Target Removal Tool")
    print("=" * 50)
    
    # Show current state
    show_current_organisms()
    
    # Remove non-human targets
    remove_non_human_targets()
    
    # Optionally remove empty organism targets
    remove_empty_organism_targets()
    
    # Show final statistics
    show_final_stats()
    
    print("\n✓ Target cleanup completed!")

if __name__ == '__main__':
    main()
