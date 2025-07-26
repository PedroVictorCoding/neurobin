"""
Import compounds from ChEMBL with filtering to exclude:
1. Compounds with empty names
2. Compounds with names containing "CHEMBL"

This provides a cleaner dataset focused on named compounds.
"""

import time
import logging
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from compounds.models import Compound

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import compounds from ChEMBL with name filtering'
    
    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NeuroeBin-FilteredImporter/1.0'
        })
        
        self.stats = {
            'fetched': 0,
            'filtered_out_empty': 0,
            'filtered_out_chembl': 0,
            'imported': 0,
            'updated': 0,
            'errors': 0
        }
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--max-compounds',
            type=int,
            default=1000,
            help='Maximum number of compounds to process'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Batch size for API requests'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.1,
            help='Delay between API calls (seconds)'
        )
        parser.add_argument(
            '--source',
            choices=['approved', 'bioactive', 'mechanisms'],
            default='approved',
            help='Source of compounds to import'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without saving'
        )
    
    def handle(self, *args, **options):
        self.stdout.write("🧬 IMPORTING FILTERED COMPOUNDS")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Source: {options['source']}")
        self.stdout.write(f"Max compounds: {options['max_compounds']}")
        self.stdout.write(f"Dry run: {options['dry_run']}")
        self.stdout.write("")
        
        if options['source'] == 'approved':
            self.import_approved_drugs(options)
        elif options['source'] == 'bioactive':
            self.import_bioactive_compounds(options)
        elif options['source'] == 'mechanisms':
            self.import_compounds_with_mechanisms(options)
        
        # Print statistics
        self.print_statistics()
    
    def make_api_call(self, url, params=None):
        """Make API call with error handling"""
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            self.stats['fetched'] += 1
            return response.json()
        except Exception as e:
            logger.error(f"API call failed: {url} - {e}")
            self.stats['errors'] += 1
            return None
    
    def import_approved_drugs(self, options):
        """Import approved drugs from ChEMBL"""
        offset = 0
        processed = 0
        
        while processed < options['max_compounds']:
            url = "https://www.ebi.ac.uk/chembl/api/data/molecule"
            params = {
                'max_phase': 4,  # Approved drugs
                'limit': options['batch_size'],
                'offset': offset,
                'format': 'json'
            }
            
            response = self.make_api_call(url, params)
            if not response or not response.get('molecules'):
                break
            
            molecules = response['molecules']
            self.stdout.write(f"Processing batch {offset//options['batch_size'] + 1} ({len(molecules)} compounds)...")
            
            for molecule in molecules:
                if processed >= options['max_compounds']:
                    break
                
                if self.process_compound(molecule, 'approved_drug', options['dry_run']):
                    processed += 1
                
                time.sleep(options['delay'])
            
            offset += options['batch_size']
    
    def import_bioactive_compounds(self, options):
        """Import bioactive compounds with known activity"""
        offset = 0
        processed = 0
        
        # First get activities, then fetch unique molecules
        compound_ids = set()
        
        while len(compound_ids) < options['max_compounds']:
            url = "https://www.ebi.ac.uk/chembl/api/data/activity"
            params = {
                'standard_type__in': 'IC50,EC50,Ki,Kd',
                'standard_value__lte': 10000,  # ≤10μM
                'limit': options['batch_size'],
                'offset': offset,
                'format': 'json'
            }
            
            response = self.make_api_call(url, params)
            if not response or not response.get('activities'):
                break
            
            activities = response['activities']
            for activity in activities:
                if activity.get('molecule_chembl_id'):
                    compound_ids.add(activity['molecule_chembl_id'])
            
            offset += options['batch_size']
        
        # Now fetch compound details
        self.stdout.write(f"Found {len(compound_ids)} unique bioactive compounds")
        
        for compound_id in list(compound_ids)[:options['max_compounds']]:
            compound_data = self.fetch_compound_details(compound_id)
            if compound_data:
                if self.process_compound(compound_data, 'bioactive', options['dry_run']):
                    processed += 1
            
            time.sleep(options['delay'])
    
    def import_compounds_with_mechanisms(self, options):
        """Import compounds with known mechanisms"""
        offset = 0
        processed = 0
        compound_ids = set()
        
        # Get mechanisms, then fetch compounds
        while len(compound_ids) < options['max_compounds']:
            url = "https://www.ebi.ac.uk/chembl/api/data/mechanism"
            params = {
                'limit': options['batch_size'],
                'offset': offset,
                'format': 'json'
            }
            
            response = self.make_api_call(url, params)
            if not response or not response.get('mechanisms'):
                break
            
            mechanisms = response['mechanisms']
            for mechanism in mechanisms:
                if mechanism.get('molecule_chembl_id'):
                    compound_ids.add(mechanism['molecule_chembl_id'])
            
            offset += options['batch_size']
        
        # Fetch compound details
        self.stdout.write(f"Found {len(compound_ids)} compounds with mechanisms")
        
        for compound_id in list(compound_ids)[:options['max_compounds']]:
            compound_data = self.fetch_compound_details(compound_id)
            if compound_data:
                if self.process_compound(compound_data, 'has_mechanism', options['dry_run']):
                    processed += 1
            
            time.sleep(options['delay'])
    
    def fetch_compound_details(self, chembl_id):
        """Fetch detailed compound information"""
        url = f"https://www.ebi.ac.uk/chembl/api/data/molecule/{chembl_id}"
        params = {'format': 'json'}
        return self.make_api_call(url, params)
    
    def process_compound(self, molecule_data, source_type, dry_run=False):
        """Process compound with filtering logic"""
        try:
            chembl_id = molecule_data.get('molecule_chembl_id')
            if not chembl_id:
                return False
            
            # Extract compound information
            pref_name = molecule_data.get('pref_name', '').strip() if molecule_data.get('pref_name') else ''
            synonyms = []
            
            # Get synonyms from molecule_synonyms
            if 'molecule_synonyms' in molecule_data:
                synonyms = [syn.get('molecule_synonym', '').strip() for syn in molecule_data['molecule_synonyms'] 
                           if syn.get('molecule_synonym') and syn.get('molecule_synonym').strip()]
            
            # Apply filtering logic
            # 1. Filter out synonyms containing "CHEMBL"
            filtered_synonyms = [syn for syn in synonyms if 'CHEMBL' not in syn.upper()]
            
            # 2. Determine primary name - prefer pref_name, then filtered synonyms
            if pref_name and 'CHEMBL' not in pref_name.upper():
                name = pref_name
            elif filtered_synonyms:
                name = filtered_synonyms[0]
            else:
                # Skip compounds with no valid names
                self.stats['filtered_out_chembl'] += 1
                if not dry_run:
                    self.stdout.write(f"  FILTERED: {chembl_id} - only CHEMBL names available")
                return False
            
            # 3. Skip compounds with empty names after filtering
            if not name or not name.strip():
                self.stats['filtered_out_empty'] += 1
                if not dry_run:
                    self.stdout.write(f"  FILTERED: {chembl_id} - empty name")
                return False
            
            aliases = ', '.join(filtered_synonyms) if filtered_synonyms else ''
            
            # Extract structure information
            smiles = ''
            if 'molecule_structures' in molecule_data:
                structures = molecule_data['molecule_structures']
                if isinstance(structures, dict):
                    smiles = structures.get('canonical_smiles', '')
                elif isinstance(structures, list) and structures:
                    smiles = structures[0].get('canonical_smiles', '')
            
            if dry_run:
                self.stdout.write(f"  WOULD IMPORT: {name} ({chembl_id})")
                return True
            
            # Create or update compound
            compound, created = Compound.objects.update_or_create(
                chembl_id=chembl_id,
                defaults={
                    'name': name,
                    'aliases': aliases,
                    'smiles': smiles,
                    'description': f"Compound from ChEMBL ({source_type})"
                }
            )
            
            if created:
                self.stats['imported'] += 1
                self.stdout.write(f"  IMPORTED: {name} ({chembl_id})")
            else:
                self.stats['updated'] += 1
                self.stdout.write(f"  UPDATED: {name} ({chembl_id})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing compound {molecule_data.get('molecule_chembl_id')}: {e}")
            self.stats['errors'] += 1
            return False
    
    def print_statistics(self):
        """Print import statistics"""
        self.stdout.write("\n📊 IMPORT STATISTICS")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Compounds fetched: {self.stats['fetched']}")
        self.stdout.write(f"Filtered out (empty names): {self.stats['filtered_out_empty']}")
        self.stdout.write(f"Filtered out (CHEMBL names): {self.stats['filtered_out_chembl']}")
        self.stdout.write(f"Successfully imported: {self.stats['imported']}")
        self.stdout.write(f"Updated existing: {self.stats['updated']}")
        self.stdout.write(f"Errors: {self.stats['errors']}")
        self.stdout.write("")
        
        total_filtered = self.stats['filtered_out_empty'] + self.stats['filtered_out_chembl']
        total_processed = self.stats['imported'] + self.stats['updated'] + total_filtered
        
        if total_processed > 0:
            filter_rate = (total_filtered / total_processed) * 100
            self.stdout.write(f"Filter rate: {filter_rate:.1f}% compounds excluded")
        
        self.stdout.write("✅ Import completed!")
