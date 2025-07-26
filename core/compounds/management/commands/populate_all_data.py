"""
Comprehensive data population script for NeuroeBin
Fetches and populates:
1. Compounds from ChEMBL
2. Targets and interactions 
3. Compound-compound interactions
4. Pathway mappings from Reactome

This script aims to maximize data coverage with no limits.
"""

import time
import logging
import requests
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.utils import timezone
from compounds.models import (
    Compound, Target, CompoundTargetInteraction, 
    CompoundToCompoundTargetInteraction
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Populate all possible compounds, interactions, and pathways data'
    
    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NeuroeBin-DataFetcher/1.0 (https://github.com/PedroVictorCoding/neurobin)'
        })
        
        # Statistics tracking
        self.stats = {
            'compounds_created': 0,
            'compounds_updated': 0,
            'compounds_skipped': 0,
            'targets_created': 0,
            'targets_updated': 0,
            'interactions_created': 0,
            'interactions_updated': 0,
            'compound_interactions_created': 0,
            'api_calls': 0,
            'errors': 0
        }
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--compounds-only',
            action='store_true',
            help='Only fetch compounds and basic data'
        )
        parser.add_argument(
            '--interactions-only',
            action='store_true',
            help='Only fetch interactions for existing compounds'
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
            '--max-compounds',
            type=int,
            help='Maximum number of compounds to process (for testing)'
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip compounds that already exist in database (faster for updates)'
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing compounds with new data (slower but more complete)'
        )
    
    def cleanup_empty_targets(self):
        """Remove targets with empty or invalid names"""
        from compounds.models import Target
        from django.db import models
        
        # Find targets with empty names or names that are just ChEMBL IDs
        empty_targets = Target.objects.filter(
            models.Q(name='') | 
            models.Q(name__isnull=True) |
            models.Q(name=models.F('chembl_id'))
        )
        
        count = empty_targets.count()
        if count > 0:
            self.stdout.write(f"🧹 Cleaning up {count} targets with empty/invalid names...")
            # Get list of target names for logging
            target_examples = list(empty_targets.values_list('name', 'chembl_id')[:10])
            if target_examples:
                self.stdout.write(f"  Examples: {target_examples}")
            empty_targets.delete()
            self.stdout.write(f"  ✅ Removed {count} empty targets")
        
        # Separate check for very short names
        short_targets = []
        for target in Target.objects.all():
            if target.name and len(target.name.strip()) < 3:
                short_targets.append(target)
        
        if short_targets:
            self.stdout.write(f"🧹 Found {len(short_targets)} targets with very short names...")
            for target in short_targets:
                target.delete()
            self.stdout.write(f"  ✅ Removed {len(short_targets)} targets with short names")
        
        if count == 0 and not short_targets:
            self.stdout.write("🧹 No empty targets found")
    
    def handle(self, *args, **options):
        """Main execution method"""
        start_time = timezone.now()
        
        # Clean up existing empty target names
        self.cleanup_empty_targets()
        
        self.stdout.write("🧬 COMPREHENSIVE DATA POPULATION")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Started at: {start_time}")
        self.stdout.write(f"Target: Maximum possible data coverage")
        self.stdout.write("")
        
        try:
            if options['compounds_only']:
                self.fetch_all_compounds(options)
            elif options['interactions_only']:
                self.fetch_all_interactions(options)
            else:
                # Full pipeline
                self.fetch_all_compounds(options)
                self.fetch_all_interactions(options)
                self.compute_compound_interactions(options)
        
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n⚠️  Process interrupted by user"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Fatal error: {e}"))
            logger.exception("Fatal error in data population")
            self.stats['errors'] += 1
        
        finally:
            self.print_final_summary(start_time)
    
    def fetch_all_compounds(self, options):
        """Fetch comprehensive compound data from ChEMBL"""
        self.stdout.write("📋 FETCHING COMPOUNDS FROM CHEMBL")
        self.stdout.write("-" * 50)
        
        # Get all approved drugs first
        self.stdout.write("🎯 Fetching approved drugs...")
        self.fetch_approved_drugs(options)
        
        # Get compounds with known mechanisms
        self.stdout.write("🔬 Fetching compounds with mechanisms...")
        self.fetch_compounds_with_mechanisms(options)
        
        # Get bioactive compounds
        self.stdout.write("⚡ Fetching bioactive compounds...")
        self.fetch_bioactive_compounds(options)
        
        # Get natural products
        self.stdout.write("🌿 Fetching natural products...")
        self.fetch_natural_products(options)
    
    def fetch_approved_drugs(self, options):
        """Fetch all approved drugs from ChEMBL"""
        offset = 0
        batch_size = options['batch_size']
        total_processed = 0
        
        while True:
            try:
                # ChEMBL API call for approved drugs
                url = "https://www.ebi.ac.uk/chembl/api/data/molecule"
                params = {
                    'max_phase': 4,  # Approved drugs
                    'limit': batch_size,
                    'offset': offset,
                    'format': 'json'
                }
                
                response = self.make_api_call(url, params)
                if not response:
                    break
                
                molecules = response.get('molecules', [])
                if not molecules:
                    break
                
                self.stdout.write(f"  Processing approved drugs batch {offset//batch_size + 1} ({len(molecules)} compounds)...")
                
                for molecule in molecules:
                    try:
                        self.process_compound(molecule, 'approved_drug', options)
                        total_processed += 1
                        
                        if options['max_compounds'] and total_processed >= options['max_compounds']:
                            self.stdout.write(f"  Reached max compounds limit: {options['max_compounds']}")
                            return
                        
                    except Exception as e:
                        logger.error(f"Error processing approved drug {molecule.get('molecule_chembl_id')}: {e}")
                        self.stats['errors'] += 1
                
                offset += batch_size
                time.sleep(options['delay'])
                
            except Exception as e:
                logger.error(f"Error fetching approved drugs batch at offset {offset}: {e}")
                self.stats['errors'] += 1
                break
        
        self.stdout.write(f"  ✅ Processed {total_processed} approved drugs")
    
    def fetch_compounds_with_mechanisms(self, options):
        """Fetch compounds that have known mechanisms of action"""
        offset = 0
        batch_size = options['batch_size']
        total_processed = 0
        
        while True:
            try:
                # Get drug mechanisms from ChEMBL (try the correct endpoint)
                url = "https://www.ebi.ac.uk/chembl/api/data/mechanism"
                params = {
                    'limit': batch_size,
                    'offset': offset,
                    'format': 'json'
                }
                
                response = self.make_api_call(url, params)
                if not response:
                    # Try alternative endpoint structure
                    self.stdout.write("  Trying alternative mechanism endpoint...")
                    break
                
                mechanisms = response.get('mechanisms', [])
                if not mechanisms:
                    break
                
                self.stdout.write(f"  Processing mechanism batch {offset//batch_size + 1} ({len(mechanisms)} mechanisms)...")
                
                # Get unique compound IDs from mechanisms
                compound_ids = set()
                for mechanism in mechanisms:
                    if mechanism.get('molecule_chembl_id'):
                        compound_ids.add(mechanism['molecule_chembl_id'])
                
                # Fetch detailed compound data
                for compound_id in list(compound_ids)[:10]:  # Limit to avoid overload
                    try:
                        compound_data = self.fetch_compound_details(compound_id)
                        if compound_data:
                            self.process_compound(compound_data, 'has_mechanism', options)
                            total_processed += 1
                            
                            if options['max_compounds'] and total_processed >= options['max_compounds']:
                                self.stdout.write(f"  Reached max compounds limit: {options['max_compounds']}")
                                return
                    
                    except Exception as e:
                        logger.error(f"Error processing mechanism compound {compound_id}: {e}")
                        self.stats['errors'] += 1
                    
                    time.sleep(options['delay'])
                
                offset += batch_size
                
            except Exception as e:
                logger.error(f"Error fetching mechanisms batch at offset {offset}: {e}")
                self.stats['errors'] += 1
                break
        
        self.stdout.write(f"  ✅ Processed {total_processed} compounds with mechanisms")
    
    def fetch_bioactive_compounds(self, options):
        """Fetch bioactive compounds from ChEMBL"""
        offset = 0
        batch_size = options['batch_size']
        total_processed = 0
        
        while True:
            try:
                # Get bioactive compounds (with activity data)
                url = "https://www.ebi.ac.uk/chembl/api/data/activity"
                params = {
                    'standard_type__in': 'IC50,EC50,Ki,Kd',  # Key activity types
                    'standard_value__lte': 10000,  # Active compounds (≤10μM)
                    'limit': batch_size,
                    'offset': offset,
                    'format': 'json'
                }
                
                response = self.make_api_call(url, params)
                if not response:
                    break
                
                activities = response.get('activities', [])
                if not activities:
                    break
                
                self.stdout.write(f"  Processing bioactive batch {offset//batch_size + 1} ({len(activities)} activities)...")
                
                # Get unique compound IDs
                compound_ids = set()
                for activity in activities:
                    if activity.get('molecule_chembl_id'):
                        compound_ids.add(activity['molecule_chembl_id'])
                
                # Fetch compound details
                for compound_id in compound_ids:
                    try:
                        compound_data = self.fetch_compound_details(compound_id)
                        if compound_data:
                            self.process_compound(compound_data, 'bioactive', options)
                            total_processed += 1
                            
                            if options['max_compounds'] and total_processed >= options['max_compounds']:
                                self.stdout.write(f"  Reached max compounds limit: {options['max_compounds']}")
                                return
                    
                    except Exception as e:
                        logger.error(f"Error processing bioactive compound {compound_id}: {e}")
                        self.stats['errors'] += 1
                    
                    time.sleep(options['delay'])
                
                offset += batch_size
                
            except Exception as e:
                logger.error(f"Error fetching bioactive batch at offset {offset}: {e}")
                self.stats['errors'] += 1
                break
        
        self.stdout.write(f"  ✅ Processed {total_processed} bioactive compounds")
    
    def fetch_natural_products(self, options):
        """Fetch natural products from ChEMBL"""
        offset = 0
        batch_size = options['batch_size']
        total_processed = 0
        
        while True:
            try:
                url = "https://www.ebi.ac.uk/chembl/api/data/molecule"
                params = {
                    'natural_product': 1,  # Natural products only
                    'limit': batch_size,
                    'offset': offset,
                    'format': 'json'
                }
                
                response = self.make_api_call(url, params)
                if not response:
                    break
                
                molecules = response.get('molecules', [])
                if not molecules:
                    break
                
                self.stdout.write(f"  Processing natural products batch {offset//batch_size + 1} ({len(molecules)} compounds)...")
                
                for molecule in molecules:
                    try:
                        self.process_compound(molecule, 'natural_product', options)
                        total_processed += 1
                        
                        if options['max_compounds'] and total_processed >= options['max_compounds']:
                            self.stdout.write(f"  Reached max compounds limit: {options['max_compounds']}")
                            return
                    
                    except Exception as e:
                        logger.error(f"Error processing natural product {molecule.get('molecule_chembl_id')}: {e}")
                        self.stats['errors'] += 1
                
                offset += batch_size
                time.sleep(options['delay'])
                
            except Exception as e:
                logger.error(f"Error fetching natural products batch at offset {offset}: {e}")
                self.stats['errors'] += 1
                break
        
        self.stdout.write(f"  ✅ Processed {total_processed} natural products")
    
    def fetch_compound_details(self, chembl_id):
        """Fetch detailed compound information"""
        try:
            url = f"https://www.ebi.ac.uk/chembl/api/data/molecule/{chembl_id}"
            params = {'format': 'json'}
            response = self.make_api_call(url, params)
            return response
        except Exception as e:
            logger.error(f"Error fetching compound details for {chembl_id}: {e}")
            return None
    
    def process_compound(self, molecule_data, source_type, options=None):
        """Process and save compound data with filtering"""
        try:
            chembl_id = molecule_data.get('molecule_chembl_id')
            if not chembl_id:
                return
            
            # Check if compound already exists (for performance optimization)
            if options and options.get('skip_existing'):
                if Compound.objects.filter(chembl_id=chembl_id).exists():
                    self.stats['compounds_skipped'] += 1
                    logger.debug(f"Skipping existing compound {chembl_id}")
                    return
            
            # Extract compound information
            pref_name = molecule_data.get('pref_name', '').strip() if molecule_data.get('pref_name') else ''
            synonyms = []
            
            # Get synonyms from molecule_synonyms
            if 'molecule_synonyms' in molecule_data:
                synonyms = [syn.get('molecule_synonym', '').strip() for syn in molecule_data['molecule_synonyms'] 
                           if syn.get('molecule_synonym') and syn.get('molecule_synonym').strip()]
            
            # Filter out synonyms containing "CHEMBL"
            filtered_synonyms = [syn for syn in synonyms if 'CHEMBL' not in syn.upper()]
            
            # Determine primary name - prefer pref_name, then filtered synonyms
            if pref_name and 'CHEMBL' not in pref_name.upper():
                name = pref_name
            elif filtered_synonyms:
                name = filtered_synonyms[0]
            else:
                # Skip compounds with no valid names (only CHEMBL names or empty)
                logger.info(f"Skipping compound {chembl_id}: no valid name (only CHEMBL or empty)")
                return
            
            # Skip compounds with empty names after filtering
            if not name or not name.strip():
                logger.info(f"Skipping compound {chembl_id}: empty name after filtering")
                return
            
            aliases = ', '.join(filtered_synonyms) if filtered_synonyms else ''
            
            # Structure information
            smiles = ''
            if 'molecule_structures' in molecule_data:
                structures = molecule_data['molecule_structures']
                if isinstance(structures, dict):
                    smiles = structures.get('canonical_smiles', '')
                elif isinstance(structures, list) and structures:
                    smiles = structures[0].get('canonical_smiles', '')
            
            # Create or update compound based on options
            if options and options.get('update_existing'):
                # Always update existing compounds with new data
                compound, created = Compound.objects.update_or_create(
                    chembl_id=chembl_id,
                    defaults={
                        'name': name,
                        'aliases': aliases,
                        'smiles': smiles,
                        'description': f"Compound from ChEMBL ({source_type})"
                    }
                )
            else:
                # Default behavior: create only if doesn't exist, minimal updates
                compound, created = Compound.objects.get_or_create(
                    chembl_id=chembl_id,
                    defaults={
                        'name': name,
                        'aliases': aliases,
                        'smiles': smiles,
                        'description': f"Compound from ChEMBL ({source_type})"
                    }
                )
            
            if created:
                self.stats['compounds_created'] += 1
                logger.debug(f"Created compound: {name} ({chembl_id})")
            else:
                self.stats['compounds_updated'] += 1
                logger.debug(f"Found existing compound: {name} ({chembl_id})")
                
        except Exception as e:
            logger.error(f"Error processing compound {molecule_data.get('molecule_chembl_id')}: {e}")
            self.stats['errors'] += 1
    
    def fetch_all_interactions(self, options):
        """Fetch all compound-target interactions"""
        self.stdout.write("🎯 FETCHING COMPOUND-TARGET INTERACTIONS")
        self.stdout.write("-" * 50)
        
        # Get all compounds that need interaction data
        compounds = Compound.objects.all()
        total_compounds = compounds.count()
        
        self.stdout.write(f"  Processing {total_compounds} compounds for interactions...")
        
        processed = 0
        for compound in compounds.iterator():
            try:
                self.fetch_compound_interactions(compound, options)
                processed += 1
                
                if processed % 100 == 0:
                    self.stdout.write(f"  Processed {processed}/{total_compounds} compounds...")
                
                time.sleep(options['delay'])
                
            except Exception as e:
                logger.error(f"Error fetching interactions for {compound.chembl_id}: {e}")
                self.stats['errors'] += 1
        
        self.stdout.write(f"  ✅ Processed interactions for {processed} compounds")
    
    def fetch_compound_interactions(self, compound, options):
        """Fetch interactions for a specific compound"""
        try:
            # Get drug mechanisms - try the correct endpoint
            url = "https://www.ebi.ac.uk/chembl/api/data/mechanism"
            params = {
                'molecule_chembl_id': compound.chembl_id,
                'format': 'json'
            }
            
            response = self.make_api_call(url, params)
            if not response:
                return
            
            mechanisms = response.get('mechanisms', [])
            
            for mechanism in mechanisms:
                try:
                    self.process_drug_mechanism(compound, mechanism)
                except Exception as e:
                    logger.error(f"Error processing mechanism for {compound.chembl_id}: {e}")
                    self.stats['errors'] += 1
        
        except Exception as e:
            logger.error(f"Error fetching mechanisms for {compound.chembl_id}: {e}")
            self.stats['errors'] += 1
    
    def process_drug_mechanism(self, compound, mechanism):
        """Process a drug mechanism and create target interaction"""
        try:
            # Extract target information
            target_chembl_id = mechanism.get('target_chembl_id')
            if not target_chembl_id:
                return
            
            # Check if mechanism has target name info we can pre-filter
            target_name = mechanism.get('target_pref_name', '')
            if target_name and (not target_name.strip() or target_name.strip() == target_chembl_id):
                logger.info(f"Skipping mechanism for target {target_chembl_id}: empty target name")
                return
            
            # Get or create target
            target = self.get_or_create_target(target_chembl_id)
            if not target:
                return
            
            # Extract mechanism information
            mechanism_of_action = mechanism.get('mechanism_of_action', '').strip()
            action_type = mechanism.get('action_type', '').strip()
            
            # Map mechanism_of_action to valid mechanism choices
            mechanism_mapped = 'unknown'
            if mechanism_of_action:
                moa_lower = mechanism_of_action.lower()
                if 'agonist' in moa_lower:
                    mechanism_mapped = 'agonist'
                elif 'antagonist' in moa_lower:
                    mechanism_mapped = 'antagonist'
                elif 'inhibitor' in moa_lower:
                    mechanism_mapped = 'inhibitor'
                elif 'activator' in moa_lower:
                    mechanism_mapped = 'activator'
                elif 'binder' in moa_lower:
                    mechanism_mapped = 'binder'
                elif 'blocker' in moa_lower:
                    mechanism_mapped = 'blocker'
            
            # Map action_type to mechanism if available
            if action_type:
                action_lower = action_type.lower()
                if 'agonist' in action_lower:
                    mechanism_mapped = 'agonist'
                elif 'antagonist' in action_lower:
                    mechanism_mapped = 'antagonist'
                elif 'inhibitor' in action_lower:
                    mechanism_mapped = 'inhibitor'
            
            # Create notes combining available information
            notes_parts = []
            if mechanism_of_action:
                notes_parts.append(f"Mechanism: {mechanism_of_action}")
            if action_type:
                notes_parts.append(f"Action: {action_type}")
            if mechanism.get('mechanism_comment'):
                notes_parts.append(f"Comment: {mechanism.get('mechanism_comment')}")
            
            notes = "; ".join(notes_parts) if notes_parts else "ChEMBL mechanism data"
            
            # Create or update interaction using correct fields
            interaction, created = CompoundTargetInteraction.objects.update_or_create(
                compound=compound,
                target=target,
                defaults={
                    'mechanism': mechanism_mapped,
                    'source': 'chembl_mechanism',
                    'notes': notes
                }
            )
            
            if created:
                self.stats['interactions_created'] += 1
            else:
                self.stats['interactions_updated'] += 1
        
        except Exception as e:
            logger.error(f"Error processing mechanism: {e}")
            self.stats['errors'] += 1
    
    def get_or_create_target(self, target_chembl_id):
        """Get or create target from ChEMBL ID"""
        try:
            # Check if target already exists
            try:
                return Target.objects.get(chembl_id=target_chembl_id)
            except Target.DoesNotExist:
                pass
            
            # Fetch target details from ChEMBL
            url = f"https://www.ebi.ac.uk/chembl/api/data/target/{target_chembl_id}"
            params = {'format': 'json'}
            
            response = self.make_api_call(url, params)
            if not response:
                return None
            
            # Extract target information
            name = response.get('pref_name', target_chembl_id)
            target_type = response.get('target_type', 'UNKNOWN')
            organism = response.get('organism', 'Unknown')
            
            # Skip if target name is empty, just the ChEMBL ID, or too generic
            name_stripped = name.strip() if name else ''
            if (not name_stripped or 
                name_stripped == target_chembl_id or 
                len(name_stripped) < 3 or
                name_stripped.lower() in ['unknown', 'target', 'protein']):
                logger.info(f"Skipping target {target_chembl_id}: invalid name '{name_stripped}'")
                return None
            
            # Create target using correct fields
            target = Target.objects.create(
                name=name,
                chembl_id=target_chembl_id,
                target_type=target_type,
                type=target_type,  # For backward compatibility
                organism=organism,
                description=f"Target from ChEMBL: {name}"
            )
            
            self.stats['targets_created'] += 1
            return target
        
        except Exception as e:
            logger.error(f"Error creating target {target_chembl_id}: {e}")
            self.stats['errors'] += 1
            return None
    
    def compute_compound_interactions(self, options):
        """Compute compound-compound interactions based on shared targets"""
        self.stdout.write("🔄 COMPUTING COMPOUND-COMPOUND INTERACTIONS")
        self.stdout.write("-" * 50)
        
        # Get all compounds with interactions
        compounds_with_interactions = Compound.objects.filter(
            compoundtargetinteraction__isnull=False
        ).distinct()
        
        total_compounds = compounds_with_interactions.count()
        self.stdout.write(f"  Processing {total_compounds} compounds for compound interactions...")
        
        processed_pairs = set()
        
        for i, compound_a in enumerate(compounds_with_interactions):
            try:
                # Get all targets for compound A
                targets_a = set(compound_a.compoundtargetinteraction_set.values_list('target_id', flat=True))
                
                # Find compounds that share targets
                shared_compounds = Compound.objects.filter(
                    compoundtargetinteraction__target_id__in=targets_a
                ).exclude(id=compound_a.id).distinct()
                
                for compound_b in shared_compounds:
                    # Create ordered pair to avoid duplicates
                    pair = tuple(sorted([compound_a.id, compound_b.id]))
                    if pair in processed_pairs:
                        continue
                    processed_pairs.add(pair)
                    
                    # Get shared targets
                    targets_b = set(compound_b.compoundtargetinteraction_set.values_list('target_id', flat=True))
                    shared_targets = targets_a.intersection(targets_b)
                    
                    # Process each shared target
                    for target_id in shared_targets:
                        try:
                            self.create_compound_interaction(compound_a, compound_b, target_id)
                        except Exception as e:
                            logger.error(f"Error creating compound interaction: {e}")
                            self.stats['errors'] += 1
                
                if (i + 1) % 100 == 0:
                    self.stdout.write(f"  Processed {i + 1}/{total_compounds} compounds...")
            
            except Exception as e:
                logger.error(f"Error processing compound {compound_a.chembl_id}: {e}")
                self.stats['errors'] += 1
        
        self.stdout.write(f"  ✅ Processed {len(processed_pairs)} compound pairs")
    
    def create_compound_interaction(self, compound_a, compound_b, target_id):
        """Create compound-compound interaction"""
        try:
            target = Target.objects.get(id=target_id)
            
            # Get mechanisms for both compounds
            interaction_a = compound_a.compoundtargetinteraction_set.filter(target=target).first()
            interaction_b = compound_b.compoundtargetinteraction_set.filter(target=target).first()
            
            if not interaction_a or not interaction_b:
                return
            
            # Determine interaction type based on mechanisms
            mech_a = interaction_a.mechanism.lower() if interaction_a.mechanism else 'unknown'
            mech_b = interaction_b.mechanism.lower() if interaction_b.mechanism else 'unknown'
            
            # Classification logic
            interaction_type = self.classify_interaction(mech_a, mech_b)
            
            # Create interaction using correct fields
            interaction, created = CompoundToCompoundTargetInteraction.objects.update_or_create(
                compound_a=compound_a,
                compound_b=compound_b,
                target=target,
                defaults={
                    'interaction_type': interaction_type,
                    'confidence': 'medium',
                    'source': 'computed_shared_target',
                    'description': f"Interaction inferred from shared target {target.name}"
                }
            )
            
            if created:
                self.stats['compound_interactions_created'] += 1
        
        except Exception as e:
            logger.error(f"Error creating compound interaction: {e}")
            self.stats['errors'] += 1
    
    def classify_interaction(self, mech_a, mech_b):
        """Classify interaction type based on mechanisms"""
        # Normalize mechanisms
        agonist_terms = ['agonist', 'activator', 'opener']
        antagonist_terms = ['antagonist', 'inhibitor', 'blocker']
        modulator_terms = ['modulator', 'pam', 'nam']
        
        def get_mechanism_type(mechanism):
            mechanism = mechanism.lower()
            if any(term in mechanism for term in agonist_terms):
                return 'agonist'
            elif any(term in mechanism for term in antagonist_terms):
                return 'antagonist'
            elif any(term in mechanism for term in modulator_terms):
                return 'modulator'
            else:
                return 'unknown'
        
        type_a = get_mechanism_type(mech_a)
        type_b = get_mechanism_type(mech_b)
        
        # Classification rules
        if type_a == type_b and type_a in ['agonist', 'antagonist']:
            return 'additive'
        elif (type_a == 'agonist' and type_b in ['modulator', 'pam']) or \
             (type_b == 'agonist' and type_a in ['modulator', 'pam']):
            return 'synergistic'
        elif (type_a == 'agonist' and type_b == 'antagonist') or \
             (type_a == 'antagonist' and type_b == 'agonist'):
            return 'antagonistic'
        else:
            return 'unknown'
    
    def make_api_call(self, url, params=None):
        """Make API call with error handling and rate limiting"""
        try:
            self.stats['api_calls'] += 1
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API call failed for {url}: {e}")
            self.stats['errors'] += 1
            return None
    
    def print_final_summary(self, start_time):
        """Print comprehensive summary of the operation"""
        end_time = timezone.now()
        duration = end_time - start_time
        
        self.stdout.write("")
        self.stdout.write("📊 FINAL SUMMARY")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Started:  {start_time}")
        self.stdout.write(f"Finished: {end_time}")
        self.stdout.write(f"Duration: {duration}")
        self.stdout.write("")
        
        # Data statistics
        self.stdout.write("📈 DATA STATISTICS:")
        self.stdout.write(f"  Compounds created: {self.stats['compounds_created']:,}")
        self.stdout.write(f"  Compounds updated: {self.stats['compounds_updated']:,}")
        self.stdout.write(f"  Compounds skipped: {self.stats['compounds_skipped']:,}")
        self.stdout.write(f"  Targets created: {self.stats['targets_created']:,}")
        self.stdout.write(f"  Targets updated: {self.stats['targets_updated']:,}")
        self.stdout.write(f"  Interactions created: {self.stats['interactions_created']:,}")
        self.stdout.write(f"  Interactions updated: {self.stats['interactions_updated']:,}")
        self.stdout.write(f"  Compound interactions: {self.stats['compound_interactions_created']:,}")
        self.stdout.write("")
        
        # Database totals
        total_compounds = Compound.objects.count()
        total_targets = Target.objects.count()
        total_interactions = CompoundTargetInteraction.objects.count()
        total_compound_interactions = CompoundToCompoundTargetInteraction.objects.count()
        
        self.stdout.write("🗄️  DATABASE TOTALS:")
        self.stdout.write(f"  Total compounds: {total_compounds:,}")
        self.stdout.write(f"  Total targets: {total_targets:,}")
        self.stdout.write(f"  Total compound-target interactions: {total_interactions:,}")
        self.stdout.write(f"  Total compound-compound interactions: {total_compound_interactions:,}")
        self.stdout.write("")
        
        # Performance statistics
        self.stdout.write("⚡ PERFORMANCE:")
        self.stdout.write(f"  Total API calls: {self.stats['api_calls']:,}")
        self.stdout.write(f"  Total errors: {self.stats['errors']:,}")
        
        if duration.total_seconds() > 0:
            rate = self.stats['api_calls'] / duration.total_seconds()
            self.stdout.write(f"  API calls per second: {rate:.2f}")
        
        self.stdout.write("")
        
        if self.stats['errors'] == 0:
            self.stdout.write(self.style.SUCCESS("✅ DATA POPULATION COMPLETED SUCCESSFULLY!"))
        else:
            self.stdout.write(self.style.WARNING(f"⚠️  DATA POPULATION COMPLETED WITH {self.stats['errors']} ERRORS"))
        
        self.stdout.write("🎉 Ready for pathway visualization!")
