"""
Django management command to update compound mechanisms of action from ChEMBL Drug Mechanisms API.

This script goes through each compound in the database and fetches/replaces their mechanisms
of action with comprehensive data from ChEMBL's Drug Mechanisms endpoint.

Usage:
    python manage.py update_compound_mechanisms
    python manage.py update_compound_mechanisms --compound-id CHEMBL25
    python manage.py update_compound_mechanisms --batch-size 10 --delay 0.5
    python manage.py update_compound_mechanisms --replace-existing
    python manage.py update_compound_mechanisms --dry-run
"""

import requests
import time
import logging
from typing import Dict, List, Optional, Tuple
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.utils.text import slugify

from compounds.models import (
    Compound, CompoundMechanismOfAction, Target, 
    ActionType, TargetType
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update compound mechanisms of action from ChEMBL Drug Mechanisms API'
    
    def __init__(self):
        super().__init__()
        self.stats = {
            'compounds_processed': 0,
            'mechanisms_created': 0,
            'mechanisms_updated': 0,
            'targets_created': 0,
            'action_types_created': 0,
            'target_types_created': 0,
            'errors': 0,
            'skipped': 0
        }
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NeuroBindDB/1.0 (https://neurobindb.com; contact@neurobindb.com)'
        })
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--compound-id',
            type=str,
            help='Update mechanisms for a specific compound ChEMBL ID (e.g., CHEMBL25)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of compounds to process in each batch (default: 50)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.2,
            help='Delay between API calls in seconds (default: 0.2)'
        )
        parser.add_argument(
            '--replace-existing',
            action='store_true',
            help='Replace existing mechanisms (default: skip compounds with mechanisms)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes'
        )
        parser.add_argument(
            '--max-compounds',
            type=int,
            help='Maximum number of compounds to process (for testing)'
        )
        parser.add_argument(
            '--start-from',
            type=int,
            default=0,
            help='Start processing from this compound index (for resuming)'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🔬 Starting compound mechanisms update from ChEMBL...')
        )
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        try:
            if options['compound_id']:
                self.update_single_compound(options['compound_id'], options)
            else:
                self.update_all_compounds(options)
            
            self.print_stats()
            
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n⚠️ Operation interrupted by user'))
            self.print_stats()
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Unexpected error: {e}')
            )
            logger.exception("Unexpected error in update_compound_mechanisms")
    
    def update_single_compound(self, chembl_id: str, options: dict):
        """Update mechanisms for a single compound"""
        try:
            compound = Compound.objects.get(chembl_id=chembl_id)
            self.stdout.write(f"📋 Updating mechanisms for {compound.name} ({chembl_id})")
            
            mechanisms = self.fetch_compound_mechanisms(chembl_id)
            if mechanisms:
                self.update_compound_mechanisms(compound, mechanisms, options)
                self.stats['compounds_processed'] += 1
            else:
                self.stdout.write(f"  ⚠️ No mechanisms found for {chembl_id}")
                self.stats['skipped'] += 1
                
        except Compound.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"❌ Compound with ChEMBL ID {chembl_id} not found in database")
            )
            self.stats['errors'] += 1
    
    def update_all_compounds(self, options: dict):
        """Update mechanisms for all compounds in database"""
        # Get compounds with ChEMBL IDs
        compounds_query = Compound.objects.exclude(
            chembl_id__isnull=True
        ).exclude(
            chembl_id__exact=''
        ).order_by('id')
        
        # Filter out compounds that already have mechanisms (unless replace_existing)
        if not options['replace_existing']:
            compounds_query = compounds_query.filter(
                mechanism_of_action__isnull=True
            )
        
        # Apply start_from offset
        start_from = options.get('start_from', 0)
        if start_from > 0:
            compounds_query = compounds_query[start_from:]
        
        total_compounds = compounds_query.count()
        self.stdout.write(f"📊 Found {total_compounds} compounds to process")
        
        if options['max_compounds']:
            compounds_query = compounds_query[:options['max_compounds']]
            self.stdout.write(f"🔢 Limited to {options['max_compounds']} compounds for testing")
        
        # Process compounds in batches
        batch_size = options['batch_size']
        
        for i in range(0, len(compounds_query), batch_size):
            batch = compounds_query[i:i + batch_size]
            self.stdout.write(f"\n🔄 Processing batch {i//batch_size + 1} ({len(batch)} compounds)...")
            
            for j, compound in enumerate(batch):
                self.stdout.write(
                    f"  [{i+j+1}/{total_compounds}] {compound.name} ({compound.chembl_id})"
                )
                
                try:
                    mechanisms = self.fetch_compound_mechanisms(compound.chembl_id)
                    if mechanisms:
                        self.update_compound_mechanisms(compound, mechanisms, options)
                        self.stats['compounds_processed'] += 1
                    else:
                        self.stdout.write("    ⚠️ No mechanisms found")
                        self.stats['skipped'] += 1
                        
                except Exception as e:
                    self.stdout.write(f"    ❌ Error: {e}")
                    logger.error(f"Error processing compound {compound.chembl_id}: {e}")
                    self.stats['errors'] += 1
                
                # Delay between requests
                time.sleep(options['delay'])
    
    def fetch_compound_mechanisms(self, chembl_id: str) -> List[Dict]:
        """Fetch drug mechanisms for a specific compound from ChEMBL API"""
        try:
            url = "https://www.ebi.ac.uk/chembl/api/data/mechanism"
            params = {
                'molecule_chembl_id': chembl_id,
                'format': 'json'
            }
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            mechanisms = data.get('mechanisms', [])
            
            self.stdout.write(f"    🔍 Found {len(mechanisms)} mechanisms")
            return mechanisms
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for {chembl_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching mechanisms for {chembl_id}: {e}")
            return []
    
    def update_compound_mechanisms(self, compound: Compound, mechanisms: List[Dict], options: dict):
        """Update compound's mechanisms of action"""
        if options['dry_run']:
            self.stdout.write(f"    🔍 DRY RUN: Would update {len(mechanisms)} mechanisms")
            return
        
        try:
            with transaction.atomic():
                # Clear existing mechanisms if replacing
                if options['replace_existing']:
                    compound.mechanism_of_action.clear()
                    self.stdout.write("    🗑️ Cleared existing mechanisms")
                
                created_mechanisms = []
                
                for mech_data in mechanisms:
                    try:
                        mechanism = self.create_or_update_mechanism(mech_data)
                        if mechanism:
                            created_mechanisms.append(mechanism)
                            
                    except Exception as e:
                        logger.error(f"Error creating mechanism: {e}")
                        self.stats['errors'] += 1
                
                # Add mechanisms to compound
                for mechanism in created_mechanisms:
                    compound.mechanism_of_action.add(mechanism)
                
                self.stdout.write(f"    ✅ Added {len(created_mechanisms)} mechanisms")
                
        except Exception as e:
            logger.error(f"Transaction failed for compound {compound.chembl_id}: {e}")
            self.stats['errors'] += 1
    
    def create_or_update_mechanism(self, mech_data: Dict) -> Optional[CompoundMechanismOfAction]:
        """Create or update a mechanism of action from ChEMBL data"""
        try:
            # Extract mechanism data
            action_type = mech_data.get('action_type', '').lower()
            mechanism_of_action = mech_data.get('mechanism_of_action', '')
            target_chembl_id = mech_data.get('target_chembl_id', '')
            
            # Get or create target
            target = None
            if target_chembl_id:
                target = self.get_or_create_target(mech_data)
            
            # Map ChEMBL action types to our choices
            interaction_type = self.map_action_type(action_type)
            target_type = self.map_target_type(mech_data.get('target_type', ''))
            
            # Create mechanism
            mechanism, created = CompoundMechanismOfAction.objects.get_or_create(
                target_name=target,
                target_type=target_type,
                target_interaction=interaction_type,
                defaults={
                    'description': f"{mechanism_of_action}. Source: ChEMBL"
                }
            )
            
            if created:
                self.stats['mechanisms_created'] += 1
                self.stdout.write(f"      ➕ Created: {mechanism}")
            else:
                self.stats['mechanisms_updated'] += 1
                self.stdout.write(f"      🔄 Updated: {mechanism}")
            
            return mechanism
            
        except Exception as e:
            logger.error(f"Error creating mechanism from data {mech_data}: {e}")
            return None
    
    def get_or_create_target(self, mech_data: Dict) -> Optional[Target]:
        """Get or create target from ChEMBL mechanism data"""
        try:
            target_chembl_id = mech_data.get('target_chembl_id', '')
            target_pref_name = mech_data.get('target_pref_name', '')
            target_type = mech_data.get('target_type', '')
            
            if not target_chembl_id or not target_pref_name:
                return None
            
            # Clean target name
            target_name = target_pref_name.strip()
            if not target_name or target_name.startswith('CHEMBL'):
                return None
            
            target, created = Target.objects.get_or_create(
                chembl_id=target_chembl_id,
                defaults={
                    'name': target_name,
                    'target_type': target_type.lower() if target_type else 'unknown',
                    'description': f"Target from ChEMBL mechanisms. Type: {target_type}"
                }
            )
            
            if created:
                self.stats['targets_created'] += 1
                self.stdout.write(f"        ➕ Created target: {target_name}")
            
            return target
            
        except Exception as e:
            logger.error(f"Error creating target from data {mech_data}: {e}")
            return None
    
    def map_action_type(self, action_type: str) -> str:
        """Map ChEMBL action types to our mechanism choices"""
        action_mapping = {
            'agonist': 'agonist',
            'antagonist': 'antagonist',
            'partial agonist': 'partial_agonist',
            'inverse agonist': 'inverse_agonist',
            'positive allosteric modulator': 'pam',
            'negative allosteric modulator': 'nam',
            'allosteric modulator': 'pam',  # Default to PAM
            'inhibitor': 'inhibitor',
            'blocker': 'antagonist',  # Map blocker to antagonist
            'activator': 'activator',
            'opener': 'activator',  # Map opener to activator
            'binder': 'binder',
            'substrate': 'binder',  # Map substrate to binder
            'cofactor': 'binder',  # Map cofactor to binder
            'upregulator': 'upregulator',
            'downregulator': 'downregulator',
            'modulator': 'binder',  # Generic modulator
        }
        
        action_type_clean = action_type.lower().strip()
        return action_mapping.get(action_type_clean, 'unknown')
    
    def map_target_type(self, target_type: str) -> str:
        """Map ChEMBL target types to our target type choices"""
        type_mapping = {
            'single protein': 'protein',
            'protein complex': 'protein',
            'protein family': 'protein',
            'enzyme': 'enzyme',
            'receptor': 'receptor',
            'ion channel': 'ion_channel',
            'transporter': 'transporter',
            'transcription factor': 'protein',
            'other': 'other',
            'unknown': 'other',
        }
        
        target_type_clean = target_type.lower().strip()
        return type_mapping.get(target_type_clean, 'other')
    
    def print_stats(self):
        """Print processing statistics"""
        self.stdout.write("\n" + "="*50)
        self.stdout.write(self.style.SUCCESS("📊 PROCESSING STATISTICS"))
        self.stdout.write("="*50)
        
        self.stdout.write(f"Compounds processed: {self.stats['compounds_processed']}")
        self.stdout.write(f"Compounds skipped: {self.stats['skipped']}")
        self.stdout.write(f"Mechanisms created: {self.stats['mechanisms_created']}")
        self.stdout.write(f"Mechanisms updated: {self.stats['mechanisms_updated']}")
        self.stdout.write(f"Targets created: {self.stats['targets_created']}")
        self.stdout.write(f"Errors encountered: {self.stats['errors']}")
        
        total_mechanisms = self.stats['mechanisms_created'] + self.stats['mechanisms_updated']
        self.stdout.write(f"\n✅ Total mechanisms processed: {total_mechanisms}")
        
        if self.stats['errors'] > 0:
            self.stdout.write(
                self.style.WARNING(f"⚠️ {self.stats['errors']} errors encountered - check logs for details")
            )
