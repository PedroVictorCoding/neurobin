"""
Management command to remove compounds containing "CHEMBL" in their names.
This provides a safe way to clean up the database with confirmation prompts.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from compounds.models import Compound


class Command(BaseCommand):
    help = 'Remove compounds containing "CHEMBL" in their names'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of compounds to delete per batch (default: 1000)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompt'
        )
    
    def handle(self, *args, **options):
        # Count compounds to be deleted
        chembl_compounds = Compound.objects.filter(name__icontains='CHEMBL')
        total_to_delete = chembl_compounds.count()
        total_compounds = Compound.objects.count()
        
        self.stdout.write("🧹 COMPOUND CLEANUP - REMOVE CHEMBL NAMES")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Total compounds in database: {total_compounds:,}")
        self.stdout.write(f"Compounds with CHEMBL in name: {total_to_delete:,}")
        self.stdout.write(f"Compounds to keep: {total_compounds - total_to_delete:,}")
        self.stdout.write(f"Percentage to delete: {(total_to_delete/total_compounds*100):.1f}%")
        self.stdout.write("")
        
        if total_to_delete == 0:
            self.stdout.write("✅ No compounds with CHEMBL names found. Nothing to delete.")
            return
        
        # Show examples
        self.stdout.write("Examples of compounds to be deleted:")
        examples = chembl_compounds[:10]
        for compound in examples:
            self.stdout.write(f"  - {compound.name} (ID: {compound.id})")
        if total_to_delete > 10:
            self.stdout.write(f"  ... and {total_to_delete - 10:,} more")
        self.stdout.write("")
        
        # Show examples of what will be kept
        kept_compounds = Compound.objects.exclude(name__icontains='CHEMBL')[:5]
        if kept_compounds.exists():
            self.stdout.write("Examples of compounds that will be kept:")
            for compound in kept_compounds:
                self.stdout.write(f"  - {compound.name} (ID: {compound.id})")
            self.stdout.write("")
        
        if options['dry_run']:
            self.stdout.write("🔍 DRY RUN MODE - No changes will be made")
            self.stdout.write(f"Would delete {total_to_delete:,} compounds")
            return
        
        # Confirmation
        if not options['force']:
            self.stdout.write("⚠️  WARNING: This action cannot be undone!")
            self.stdout.write(f"Are you sure you want to delete {total_to_delete:,} compounds?")
            response = input("Type 'yes' to confirm, anything else to cancel: ")
            
            if response.lower() != 'yes':
                self.stdout.write("❌ Operation cancelled.")
                return
        
        # Perform deletion in batches
        self.stdout.write(f"🗑️  Deleting compounds in batches of {options['batch_size']:,}...")
        
        deleted_total = 0
        batch_num = 1
        
        with transaction.atomic():
            while True:
                # Get a batch of compounds to delete
                batch = list(chembl_compounds[:options['batch_size']].values_list('id', flat=True))
                
                if not batch:
                    break
                
                # Delete the batch
                deleted_count = Compound.objects.filter(id__in=batch).delete()[0]
                deleted_total += deleted_count
                
                self.stdout.write(f"  Batch {batch_num}: Deleted {deleted_count:,} compounds")
                batch_num += 1
        
        # Final statistics
        remaining_compounds = Compound.objects.count()
        
        self.stdout.write("")
        self.stdout.write("✅ DELETION COMPLETED")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Compounds deleted: {deleted_total:,}")
        self.stdout.write(f"Compounds remaining: {remaining_compounds:,}")
        self.stdout.write("")
        
        # Verify no CHEMBL compounds remain
        remaining_chembl = Compound.objects.filter(name__icontains='CHEMBL').count()
        if remaining_chembl == 0:
            self.stdout.write("✅ All compounds with CHEMBL names have been removed!")
        else:
            self.stdout.write(f"⚠️  Warning: {remaining_chembl} compounds with CHEMBL names still remain")
