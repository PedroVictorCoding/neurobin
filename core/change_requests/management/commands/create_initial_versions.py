from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from compounds.models import Compound
from change_requests.models import CompoundVersion


class Command(BaseCommand):
    help = 'Create initial versions for existing compounds'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force creation even if versions already exist',
        )
    
    def handle(self, *args, **options):
        compounds = Compound.objects.all()
        system_user = User.objects.filter(is_superuser=True).first()
        
        if not system_user:
            self.stdout.write(
                self.style.ERROR('No superuser found. Please create a superuser first.')
            )
            return
        
        created_count = 0
        skipped_count = 0
        
        for compound in compounds:
            # Check if compound already has versions
            existing_versions = CompoundVersion.objects.filter(compound=compound).exists()
            
            if existing_versions and not options['force']:
                skipped_count += 1
                continue
            
            # Create initial version
            version = CompoundVersion.create_snapshot(
                compound=compound,
                created_by=system_user,
                notes="Initial version created by system"
            )
            
            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created version {version.version_number} for compound "{compound.name}"'
                )
            )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Completed. Created {created_count} versions, skipped {skipped_count} compounds.'
            )
        )
