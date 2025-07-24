"""
Django management command to import compound-target interaction data from ChEMBL API.

This command fetches compound-target interactions from ChEMBL's official API and populates:
- Target models with target information
- CompoundTargetInteraction models with mechanism data  
- CompoundToCompoundTargetInteraction models for shared target analysis

Usage:
    python manage.py import_chembl_interactions --compounds=CHEMBL25,CHEMBL154
    python manage.py import_chembl_interactions --all-compounds
    python manage.py import_chembl_interactions --file=compound_ids.txt
"""

import json
import time
from typing import List, Dict, Optional, Set, Tuple
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from compounds.models import (
    Compound, Target, CompoundTargetInteraction, CompoundToCompoundTargetInteraction,
    ActionType, TargetType
)

try:
    import requests
except ImportError:
    raise CommandError(
        "The 'requests' library is required for this command. "
        "Install it with: pip install requests"
    )


class ChEMBLImporter:
    """ChEMBL API client for fetching compound-target interaction data."""
    
    BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"
    
    # Mechanism normalization mapping
    MECHANISM_MAPPING = {
        'agonist': 'agonist',
        'partial agonist': 'agonist', 
        'full agonist': 'agonist',
        'antagonist': 'antagonist',
        'competitive antagonist': 'antagonist',
        'non-competitive antagonist': 'antagonist',
        'inhibitor': 'inhibitor',
        'competitive inhibitor': 'inhibitor',
        'non-competitive inhibitor': 'inhibitor',
        'reversible inhibitor': 'inhibitor',
        'irreversible inhibitor': 'inhibitor',
        'substrate': 'substrate',
        'inducer': 'inducer',
        'modulator': 'modulator',
        'positive modulator': 'modulator',
        'negative modulator': 'modulator',
        'blocker': 'blocker',
        'channel blocker': 'blocker',
        'opener': 'opener',
        'activator': 'activator',
    }
    
    def __init__(self, slow_mode: bool = False):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Neurobin-ChEMBL-Importer/1.0',
            'Accept': 'application/json'
        })
        self.slow_mode = slow_mode
        # Initialize standard types on first use
        self._action_types_initialized = False
        self._target_types_initialized = False
    
    def ensure_action_types(self):
        """Ensure standard ActionType entries exist."""
        if self._action_types_initialized:
            return
        
        standard_action_types = [
            ('agonist', 'Agonist', 'Activates the target by binding to the active site', 'activation'),
            ('antagonist', 'Antagonist', 'Blocks target activity by competitive binding', 'inhibition'),
            ('partial_agonist', 'Partial Agonist', 'Partially activates the target', 'modulation'),
            ('inverse_agonist', 'Inverse Agonist', 'Reduces target activity below baseline', 'inhibition'),
            ('inhibitor', 'Inhibitor', 'Prevents or reduces target activity', 'inhibition'),
            ('activator', 'Activator', 'Increases target activity or function', 'activation'),
            ('modulator', 'Modulator', 'Alters target activity (positive or negative)', 'modulation'),
            ('blocker', 'Blocker', 'Blocks target function or pathway', 'inhibition'),
            ('opener', 'Opener', 'Opens or activates channels/gates', 'activation'),
            ('inducer', 'Inducer', 'Increases expression or production of target', 'activation'),
            ('substrate', 'Substrate', 'Acts as a substrate for enzymatic activity', 'interaction'),
            ('binder', 'Binder', 'Binds to target without clear functional effect', 'interaction'),
            ('pam', 'Positive Allosteric Modulator', 'Enhances target activity through allosteric binding', 'modulation'),
            ('nam', 'Negative Allosteric Modulator', 'Reduces target activity through allosteric binding', 'modulation'),
            ('unknown', 'Unknown', 'Mechanism of action not determined', 'unknown'),
        ]
        
        for name, display_name, description, category in standard_action_types:
            ActionType.objects.get_or_create(
                name=name,
                defaults={
                    'display_name': display_name,
                    'description': description,
                    'category': category
                }
            )
        
        self._action_types_initialized = True
    
    def ensure_target_types(self):
        """Ensure standard TargetType entries exist."""
        if self._target_types_initialized:
            return
        
        standard_target_types = [
            ('receptor', 'Receptor', 'Membrane or intracellular proteins that bind signaling molecules', 'membrane'),
            ('enzyme', 'Enzyme', 'Proteins that catalyze biochemical reactions', 'catalytic'),
            ('ion_channel', 'Ion Channel', 'Membrane proteins that allow selective ion passage', 'membrane'),
            ('transporter', 'Transporter', 'Proteins that move substances across membranes', 'membrane'),
            ('protein', 'Protein', 'General protein targets', 'protein'),
            ('single_protein', 'Single Protein', 'Individual protein targets', 'protein'),
            ('protein_complex', 'Protein Complex', 'Multi-subunit protein assemblies', 'protein'),
            ('protein_family', 'Protein Family', 'Groups of related proteins', 'protein'),
            ('cell_line', 'Cell Line', 'Cultured cell systems', 'cellular'),
            ('tissue', 'Tissue', 'Organized cellular structures', 'cellular'),
            ('organism', 'Organism', 'Whole organism targets', 'organism'),
            ('unknown', 'Unknown', 'Target type not determined', 'unknown'),
            ('other', 'Other', 'Other target types not listed', 'other'),
        ]
        
        for name, display_name, description, category in standard_target_types:
            TargetType.objects.get_or_create(
                name=name,
                defaults={
                    'display_name': display_name,
                    'description': description,
                    'category': category
                }
            )
        
        self._target_types_initialized = True
    
    def get_or_create_action_type(self, mechanism_str: str) -> ActionType:
        """Get or create ActionType from mechanism string."""
        self.ensure_action_types()
        
        # Normalize the mechanism string
        normalized = self.normalize_mechanism(mechanism_str)
        
        # Try to find existing ActionType
        action_type = ActionType.objects.filter(name=normalized).first()
        if action_type:
            return action_type
        
        # If not found, create with the original string as display name
        action_type, created = ActionType.objects.get_or_create(
            name=normalized,
            defaults={
                'display_name': mechanism_str.title() if mechanism_str else 'Unknown',
                'description': f'Parsed from ChEMBL: {mechanism_str}',
                'category': 'unknown'
            }
        )
        
        return action_type
    
    def get_or_create_target_type(self, target_type_str: str) -> TargetType:
        """Get or create TargetType from ChEMBL target type string."""
        self.ensure_target_types()
        
        # Normalize target type string
        if not target_type_str:
            target_type_str = 'unknown'
        
        normalized = target_type_str.lower().strip().replace(' ', '_')
        
        # Try to find existing TargetType
        target_type = TargetType.objects.filter(name=normalized).first()
        if target_type:
            return target_type
        
        # If not found, create with the original string as display name
        target_type, created = TargetType.objects.get_or_create(
            name=normalized,
            defaults={
                'display_name': target_type_str.title() if target_type_str else 'Unknown',
                'description': f'Parsed from ChEMBL: {target_type_str}',
                'category': 'unknown'
            }
        )
        
        return target_type
    
    def fetch_with_retry(self, url: str, params: Dict = None, max_retries: int = 3) -> Optional[Dict]:
        """Fetch data from ChEMBL API with retry logic."""
        for attempt in range(max_retries):
            try:
                # Add extra delay in slow mode
                if self.slow_mode and attempt > 0:
                    time.sleep(5)  # Longer wait between retries in slow mode
                
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                print(f"[!] API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # Exponential backoff with longer delays in slow mode
                    delay = (2 ** attempt) * (3 if self.slow_mode else 1)
                    time.sleep(delay)
                else:
                    print(f"[✗] Failed to fetch data from {url}")
                    return None
    
    def get_compound_mechanisms(self, chembl_id: str) -> List[Dict]:
        """Fetch comprehensive mechanism data for a compound from both mechanism and activity endpoints."""
        mechanisms = []
        
        # 1. Get explicit mechanisms from ChEMBL mechanism endpoint
        url = f"{self.BASE_URL}/mechanism.json"
        params = {'molecule_chembl_id': chembl_id, 'limit': 50}
        
        data = self.fetch_with_retry(url, params)
        if data:
            explicit_mechanisms = data.get('mechanisms', [])
            for mech in explicit_mechanisms:
                mechanisms.append({
                    **mech,
                    'source': 'mechanism',
                    'priority': 1  # Explicit mechanisms have highest priority
                })
        
        # 2. Get high-affinity targets from activity data
        activity_url = f"{self.BASE_URL}/activity.json"
        activity_params = {
            'molecule_chembl_id': chembl_id,
            'limit': 100,
            'standard_type__in': 'IC50,EC50,Ki,Kd,pIC50,pEC50,pKi,pKd',
            'target_type': 'SINGLE PROTEIN'  # Focus on single protein targets
        }
        
        activity_data = self.fetch_with_retry(activity_url, activity_params)
        if activity_data:
            activities = activity_data.get('activities', [])
            
            # Group by target and find best affinity
            target_affinities = {}
            for activity in activities:
                target_id = activity.get('target_chembl_id')
                if not target_id:
                    continue
                
                # Convert activity values to comparable format (lower is better for IC50/Ki)
                standard_value = activity.get('standard_value')
                standard_type = activity.get('standard_type', '').lower()
                pchembl_value = activity.get('pchembl_value')
                
                if not standard_value and not pchembl_value:
                    continue
                
                # Use pChEMBL value if available (higher is better), otherwise convert standard value
                if pchembl_value:
                    affinity_score = float(pchembl_value)
                elif standard_value:
                    try:
                        value = float(standard_value)
                        # Convert to pValue (higher is better)
                        if value > 0:
                            import math
                            if standard_type.startswith('p'):
                                affinity_score = value  # Already a p-value
                            else:
                                # Convert to -log10(value in M)
                                # Assume nM if no units specified
                                value_in_m = value / 1e9 if value > 1 else value / 1e6
                                affinity_score = -math.log10(value_in_m)
                        else:
                            continue
                    except (ValueError, TypeError):
                        continue
                else:
                    continue
                
                # Keep the best affinity for each target
                if target_id not in target_affinities or affinity_score > target_affinities[target_id]['affinity']:
                    target_affinities[target_id] = {
                        'affinity': affinity_score,
                        'target_pref_name': activity.get('target_pref_name', ''),
                        'standard_type': standard_type,
                        'standard_value': standard_value,
                        'pchembl_value': pchembl_value,
                        'assay_description': activity.get('assay_description', '')
                    }
            
            # Add high-affinity targets as mechanisms (affinity > 6.0 pValue = < 1μM)
            for target_id, data in target_affinities.items():
                if data['affinity'] >= 6.0:  # High affinity threshold
                    # Skip if we already have this target from explicit mechanisms
                    existing_targets = [m.get('target_chembl_id') for m in mechanisms]
                    if target_id not in existing_targets:
                        mechanisms.append({
                            'target_chembl_id': target_id,
                            'mechanism_of_action': f"High affinity binding (pActivity: {data['affinity']:.1f})",
                            'source': 'activity',
                            'priority': 2,  # Activity-derived mechanisms have lower priority
                            'affinity_score': data['affinity'],
                            'target_pref_name': data['target_pref_name'],
                            'assay_info': data['assay_description'][:100] if data['assay_description'] else ''
                        })
        
        # Sort by priority (explicit mechanisms first) then by affinity
        mechanisms.sort(key=lambda x: (
            x.get('priority', 3),
            -x.get('affinity_score', 0)
        ))
        
        return mechanisms[:15]  # Return top 15 most relevant mechanisms
    
    def get_compound_activities(self, chembl_id: str) -> List[Dict]:
        """Fetch activity data for affinity level calculation."""
        url = f"{self.BASE_URL}/activity.json"
        params = {
            'molecule_chembl_id': chembl_id,
            'limit': 100,
            'standard_type__in': 'IC50,EC50,Ki,Kd'
        }
        
        data = self.fetch_with_retry(url, params)
        if not data:
            return []
        
        return data.get('activities', [])
    
    def get_target_details(self, target_chembl_id: str) -> Optional[Dict]:
        """Fetch detailed target information."""
        url = f"{self.BASE_URL}/target/{target_chembl_id}.json"
        
        return self.fetch_with_retry(url)
    
    def normalize_mechanism(self, mechanism: str) -> str:
        """Normalize mechanism terms to standard choices."""
        if not mechanism:
            return 'unknown'
        
        mechanism_lower = mechanism.lower().strip()
        
        # Direct mapping
        if mechanism_lower in self.MECHANISM_MAPPING:
            return self.MECHANISM_MAPPING[mechanism_lower]
        
        # Fuzzy matching
        for key, value in self.MECHANISM_MAPPING.items():
            if key in mechanism_lower:
                return value
        
        return 'unknown'
    
    def calculate_affinity_level(self, activities: List[Dict]) -> str:
        """Calculate affinity level based on IC50/EC50/Ki/Kd values."""
        if not activities:
            return 'unknown'
        
        min_value = float('inf')
        
        for activity in activities:
            value = activity.get('standard_value')
            unit = activity.get('standard_units')
            
            if not value or not unit:
                continue
            
            try:
                value = float(value)
                unit = unit.upper()
                
                # Convert to nM if needed
                if unit == 'M':
                    value *= 1e9
                elif unit == 'UM' or unit == 'µM':
                    value *= 1000
                elif unit == 'MM':
                    value *= 1e6
                elif unit == 'NM':
                    pass  # Already in nM
                else:
                    continue  # Skip unknown units
                
                min_value = min(min_value, value)
                
            except (ValueError, TypeError):
                continue
        
        if min_value == float('inf'):
            return 'unknown'
        elif min_value < 100:
            return 'high'
        elif min_value < 1000:
            return 'medium'
        else:
            return 'low'
    
    def get_compound_by_name(self, name: str) -> Optional[str]:
        """Search for a compound by name and return its ChEMBL ID."""
        url = f"{self.BASE_URL}/molecule.json"
        params = {
            'molecule_synonyms__molecule_synonym__iexact': name,
            'limit': 5  # Get top 5 matches
        }
        
        data = self.fetch_with_retry(url, params)
        if not data or not data.get('molecules'):
            # Try alternative search by preferred name
            params = {
                'pref_name__iexact': name,
                'limit': 5
            }
            data = self.fetch_with_retry(url, params)
        
        if not data or not data.get('molecules'):
            # Try fuzzy search
            params = {
                'molecule_synonyms__molecule_synonym__icontains': name,
                'limit': 10
            }
            data = self.fetch_with_retry(url, params)
        
        if data and data.get('molecules'):
            molecules = data['molecules']
            # Return the first match's ChEMBL ID
            return molecules[0].get('molecule_chembl_id')
        
        return None
    
    def search_compounds_by_names(self, names: List[str]) -> Dict[str, str]:
        """Search for multiple compounds by name and return a mapping of name -> ChEMBL ID."""
        results = {}
        
        for name in names:
            name = name.strip()
            if not name:
                continue
            
            print(f"[→] Searching ChEMBL for compound: {name}")
            
            # Add delay in slow mode
            if self.slow_mode:
                time.sleep(2)
            
            chembl_id = self.get_compound_by_name(name)
            
            if chembl_id:
                results[name] = chembl_id
                print(f"[✓] Found {name} → {chembl_id}")
            else:
                print(f"[!] No ChEMBL match found for: {name}")
        
        return results
    
    def get_current_date(self) -> str:
        """Get current date for import timestamps."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
    
    def get_drug_indications(self, chembl_id: str) -> List[Dict]:
        """Get drug indications for a compound from ChEMBL."""
        url = f"{self.BASE_URL}/drug_indication.json"
        params = {'molecule_chembl_id': chembl_id, 'limit': 20}
        
        try:
            data = self.fetch_with_retry(url, params)
            if data and 'drug_indications' in data:
                indications = data['drug_indications']
                # Sort by max phase (higher phases are more advanced/important)
                def get_phase_value(indication):
                    phase = indication.get('max_phase_for_ind', 0)
                    if phase is None:
                        return 0
                    try:
                        return float(phase)
                    except (ValueError, TypeError):
                        return 0
                
                sorted_indications = sorted(
                    indications, 
                    key=get_phase_value, 
                    reverse=True
                )
                return sorted_indications[:3]  # Return top 3
            return []
        except Exception as e:
            print(f"[!] Error fetching indications for {chembl_id}: {e}")
            return []
    
    def get_atc_classifications(self, chembl_id: str) -> List[Dict]:
        """Get ATC (Anatomical Therapeutic Chemical) classifications for a compound from ChEMBL."""
        url = f"{self.BASE_URL}/drug.json"
        params = {'molecule_chembl_id': chembl_id, 'limit': 10}
        
        try:
            data = self.fetch_with_retry(url, params)
            if data and 'drugs' in data and data['drugs']:
                # Get the first drug entry (should be only one for specific ChEMBL ID)
                drug_data = data['drugs'][0]
                atc_classifications = drug_data.get('atc_classification', [])
                return atc_classifications
            return []
        except Exception as e:
            print(f"[!] Error fetching ATC codes for {chembl_id}: {e}")
            return []
    
    def get_drug_families_from_atc(self, atc_codes: List[Dict]) -> List[str]:
        """Extract drug family names from ATC classification codes."""
        families = []
        
        # ATC code structure: First letter = Anatomical main group
        # Second level (first two chars) = Therapeutic subgroup
        # Third level (first three chars) = Pharmacological subgroup
        # Fourth level (first four chars) = Chemical subgroup
        # Fifth level (full code) = Chemical substance
        
        atc_to_family = {
            # A - Alimentary tract and metabolism
            'A01': 'Dental Preparations',
            'A02': 'Antacids',
            'A03': 'Antispasmodics',
            'A04': 'Antiemetics',
            'A05': 'Bile Therapy',
            'A06': 'Laxatives',
            'A07': 'Antidiarrheals',
            'A08': 'Anti-obesity',
            'A09': 'Digestives',
            'A10': 'Antidiabetics',
            'A11': 'Vitamins',
            'A12': 'Mineral Supplements',
            'A13': 'Tonics',
            'A14': 'Anabolic Agents',
            'A16': 'Other Alimentary Drugs',
            
            # B - Blood and blood forming organs
            'B01': 'Antithrombotics',
            'B02': 'Antihemorrhagics',
            'B03': 'Antianemics',
            'B05': 'Blood Substitutes',
            'B06': 'Other Hematological',
            
            # C - Cardiovascular system
            'C01': 'Cardiac Therapy',
            'C02': 'Antihypertensives',
            'C03': 'Diuretics',
            'C04': 'Peripheral Vasodilators',
            'C05': 'Vasoprotectives',
            'C07': 'Beta Blockers',
            'C08': 'Calcium Channel Blockers',
            'C09': 'ACE Inhibitors',
            'C10': 'Lipid Modifying Agents',
            
            # D - Dermatologicals
            'D01': 'Antifungals (Dermatological)',
            'D02': 'Emollients',
            'D03': 'Burns Treatment',
            'D04': 'Anti-pruritics',
            'D05': 'Anti-psoriatics',
            'D06': 'Antibiotics (Dermatological)',
            'D07': 'Corticosteroids (Dermatological)',
            'D08': 'Antiseptics',
            'D09': 'Medicated Dressings',
            'D10': 'Anti-acne',
            'D11': 'Other Dermatological',
            
            # G - Genitourinary system and sex hormones
            'G01': 'Gynecological Anti-infectives',
            'G02': 'Other Gynecological',
            'G03': 'Sex Hormones',
            'G04': 'Urological',
            
            # H - Systemic hormonal preparations
            'H01': 'Pituitary Hormones',
            'H02': 'Corticosteroids',
            'H03': 'Thyroid Therapy',
            'H04': 'Pancreatic Hormones',
            'H05': 'Calcium Homeostasis',
            
            # J - Antiinfectives for systemic use
            'J01': 'Antibacterials',
            'J02': 'Antimycotics',
            'J04': 'Antimycobacterials',
            'J05': 'Antivirals',
            'J06': 'Immune Sera',
            'J07': 'Vaccines',
            
            # L - Antineoplastic and immunomodulating agents
            'L01': 'Antineoplastics',
            'L02': 'Endocrine Therapy',
            'L03': 'Immunostimulants',
            'L04': 'Immunosuppressants',
            
            # M - Musculo-skeletal system
            'M01': 'Anti-inflammatory',
            'M02': 'Topical Anti-rheumatic',
            'M03': 'Muscle Relaxants',
            'M04': 'Antigout',
            'M05': 'Bone Diseases',
            'M09': 'Other Musculo-skeletal',
            
            # N - Nervous system
            'N01': 'Anesthetics',
            'N02': 'Analgesics',
            'N03': 'Antiepileptics',
            'N04': 'Anti-Parkinson',
            'N05': 'Psycholeptics',
            'N06': 'Psychoanaleptics',
            'N07': 'Other Nervous System',
            
            # P - Antiparasitic products
            'P01': 'Antiprotozoals',
            'P02': 'Anthelmintics',
            'P03': 'Ectoparasiticides',
            
            # R - Respiratory system
            'R01': 'Nasal Preparations',
            'R02': 'Throat Preparations',
            'R03': 'Obstructive Airway Diseases',
            'R05': 'Cough and Cold',
            'R06': 'Antihistamines',
            'R07': 'Other Respiratory',
            
            # S - Sensory organs
            'S01': 'Ophthalmologicals',
            'S02': 'Otologicals',
            'S03': 'Ophthalmological and Otological',
            
            # V - Various
            'V01': 'Allergens',
            'V03': 'All Other Therapeutic Products',
            'V04': 'Diagnostic Agents',
            'V06': 'General Nutrients',
            'V07': 'All Other Non-therapeutic Products',
            'V08': 'Contrast Media',
            'V09': 'Diagnostic Radiopharmaceuticals',
            'V10': 'Therapeutic Radiopharmaceuticals',
            'V20': 'Surgical Dressings',
        }
        
        # More specific mappings for common drug subclasses
        specific_mappings = {
            'N05A': 'Antipsychotics',
            'N05B': 'Anxiolytics', 
            'N05C': 'Hypnotics and Sedatives',
            'N06A': 'Antidepressants',
            'N06B': 'Psychostimulants',
            'C07A': 'Beta Blockers',
            'C08C': 'Calcium Channel Blockers',
            'C09A': 'ACE Inhibitors',
            'C09C': 'Angiotensin II Antagonists',
            'C10A': 'Statins',
            'J01C': 'Beta-lactam Antibacterials',
            'J01D': 'Cephalosporins',
            'J01F': 'Macrolides',
            'J01G': 'Aminoglycosides',
            'J01M': 'Quinolone Antibacterials',
            'M01A': 'NSAIDs',
            'A10A': 'Insulins',
            'A10B': 'Blood Glucose Lowering Drugs',
        }
        
        for atc_data in atc_codes:
            atc_code = atc_data.get('code', '')
            description = atc_data.get('description', '')
            
            if atc_code:
                # First try specific mappings (4 chars)
                if len(atc_code) >= 4:
                    prefix_4 = atc_code[:4]
                    if prefix_4 in specific_mappings:
                        families.append(specific_mappings[prefix_4])
                        continue
                
                # Then try 3-char mappings
                if len(atc_code) >= 3:
                    prefix_3 = atc_code[:3]
                    if prefix_3 in atc_to_family:
                        families.append(atc_to_family[prefix_3])
                        continue
                
                # If no mapping found, try to extract from description
                if description:
                    # Extract the last part of the description which is usually the specific class
                    desc_parts = description.split(':')
                    if len(desc_parts) > 1:
                        family_name = desc_parts[-1].strip()
                        if family_name and len(family_name) > 3:
                            families.append(family_name)
        
        return list(set(families))  # Remove duplicates


class Command(BaseCommand):
    help = 'Import compound-target interaction data from ChEMBL API'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--compounds',
            type=str,
            help='Comma-separated list of ChEMBL IDs (e.g., CHEMBL25,CHEMBL154)'
        )
        parser.add_argument(
            '--file',
            type=str,
            help='Path to file containing ChEMBL IDs (one per line)'
        )
        parser.add_argument(
            '--all-compounds',
            action='store_true',
            help='Import data for all compounds in database with ChEMBL IDs'
        )
        parser.add_argument(
            '--create-compound-interactions',
            action='store_true',
            default=True,
            help='Create compound-to-compound interactions for shared targets'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Number of compounds to process in each batch'
        )
        parser.add_argument(
            '--slow-mode',
            action='store_true',
            help='Enable slow mode with longer delays to prevent API blocking'
        )
        parser.add_argument(
            '--search-names',
            type=str,
            help='Comma-separated list of compound names to search for in ChEMBL'
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing compounds with enhanced ChEMBL data (descriptions, categories, mechanisms)'
        )
        parser.add_argument(
            '--match-by-name',
            action='store_true',
            help='When updating, also try to match existing compounds by name (not just ChEMBL ID)'
        )
        parser.add_argument(
            '--normalize-names',
            action='store_true',
            help='Normalize existing compound names to proper capitalization (e.g., DIAZEPAM → Diazepam)'
        )
    
    def handle(self, *args, **options):
        importer = ChEMBLImporter(slow_mode=options['slow_mode'])
        
        # Get list of ChEMBL IDs to process
        chembl_ids = self.get_chembl_ids(options)
        
        if not chembl_ids:
            raise CommandError("No ChEMBL IDs specified. Use --compounds, --file, or --all-compounds")
        
        if options['slow_mode']:
            self.stdout.write(self.style.WARNING('[i] Slow mode enabled - using extended delays to prevent API blocking'))
        
        if options['update_existing']:
            self.stdout.write(self.style.WARNING('[i] Update existing enabled - will enhance existing compounds with ChEMBL data'))
        
        if options['match_by_name']:
            self.stdout.write(self.style.WARNING('[i] Name matching enabled - will try to match existing compounds by name'))
        
        # Handle normalize-names option
        if options['normalize_names']:
            self.normalize_existing_compound_names()
            return
        
        self.stdout.write(f"[i] Processing {len(chembl_ids)} compounds...")
        
        # Process compounds in batches
        batch_size = options['batch_size']
        slow_mode = options['slow_mode']
        update_existing = options['update_existing']
        match_by_name = options['match_by_name']
        
        for i in range(0, len(chembl_ids), batch_size):
            batch = chembl_ids[i:i + batch_size]
            self.process_batch(importer, batch, slow_mode, update_existing, match_by_name)
            
            if i + batch_size < len(chembl_ids):
                # Determine delay based on mode
                delay = 10 if slow_mode else 2
                self.stdout.write(f"[i] Processed {i + batch_size}/{len(chembl_ids)}, sleeping {delay}s...")
                time.sleep(delay)  # Rate limiting
        
        # Create compound-to-compound interactions
        if options['create_compound_interactions']:
            self.create_compound_interactions()
        
        self.stdout.write(self.style.SUCCESS('[✓] Import completed successfully!'))
    
    def get_chembl_ids(self, options) -> List[str]:
        """Get list of ChEMBL IDs based on command options."""
        chembl_ids = []
        
        # Handle search by compound names
        if options.get('search_names'):
            self.stdout.write(self.style.SUCCESS(f"🔍 Searching ChEMBL for compound names..."))
            
            names = [name.strip() for name in options['search_names'].split(',')]
            importer = ChEMBLImporter(slow_mode=options.get('slow_mode', False))
            name_to_id_mapping = importer.search_compounds_by_names(names)
            
            if not name_to_id_mapping:
                raise CommandError("❌ No compounds found for the provided names")
            
            # Display mapping
            self.stdout.write("\n📋 Name → ChEMBL ID Mapping:")
            for name, chembl_id in name_to_id_mapping.items():
                self.stdout.write(f"   • {name} → {chembl_id}")
            
            chembl_ids.extend(name_to_id_mapping.values())
        
        # Handle direct ChEMBL IDs
        if options['compounds']:
            chembl_ids.extend([id.strip() for id in options['compounds'].split(',')])
        
        elif options['file']:
            try:
                with open(options['file'], 'r') as f:
                    chembl_ids.extend([line.strip() for line in f if line.strip()])
            except FileNotFoundError:
                raise CommandError(f"File not found: {options['file']}")
        
        elif options['all_compounds']:
            # Get all compounds with ChEMBL IDs
            compounds = Compound.objects.filter(
                chembl_id__isnull=False
            ).exclude(chembl_id='')
            chembl_ids.extend([c.chembl_id for c in compounds])
        
        elif options.get('update_existing'):
            # Get all compounds that could benefit from ChEMBL enhancement
            if options.get('match_by_name'):
                # Include compounds without ChEMBL IDs for name matching
                compounds = Compound.objects.all()
                # For compounds without ChEMBL ID, we'll try name search
                for compound in compounds:
                    if compound.chembl_id:
                        chembl_ids.append(compound.chembl_id)
                    elif options.get('match_by_name'):
                        # Try to find ChEMBL ID by name search
                        name_search_importer = ChEMBLImporter(slow_mode=options.get('slow_mode', False))
                        found_id = name_search_importer.get_compound_by_name(compound.name)
                        if found_id:
                            chembl_ids.append(found_id)
                            self.stdout.write(f"[i] Found ChEMBL ID for {compound.name}: {found_id}")
            else:
                # Only compounds with existing ChEMBL IDs
                compounds = Compound.objects.filter(
                    chembl_id__isnull=False
                ).exclude(chembl_id='')
                chembl_ids.extend([c.chembl_id for c in compounds])
        
        elif not chembl_ids:  # No search names and no other options
            # Default test compounds
            chembl_ids = [
                "CHEMBL25",     # Caffeine
                "CHEMBL154",    # Fluoxetine
                "CHEMBL1487",   # Modafinil
                "CHEMBL2103745", # TAK-653
                "CHEMBL112",    # LSD
                "CHEMBL122",    # Ketamine
                "CHEMBL2153138" # Psilocybin
            ]
        
        return chembl_ids
    
    def process_batch(self, importer: ChEMBLImporter, chembl_ids: List[str], slow_mode: bool = False, update_existing: bool = False, match_by_name: bool = False):
        """Process a batch of compounds."""
        for chembl_id in chembl_ids:
            try:
                self.process_compound(importer, chembl_id, slow_mode, update_existing, match_by_name)
            except Exception as e:
                self.stdout.write(f"[✗] Error processing {chembl_id}: {e}")
    
    def process_compound(self, importer: ChEMBLImporter, chembl_id: str, slow_mode: bool = False, update_existing: bool = False, match_by_name: bool = False):
        """Process a single compound."""
        self.stdout.write(f"[→] Processing {chembl_id}...")
        
        # Get or create compound from ChEMBL data
        compound = self.get_or_create_compound(importer, chembl_id, slow_mode, update_existing, match_by_name)
        if not compound:
            self.stdout.write(f"[!] Could not fetch/create compound {chembl_id} from ChEMBL")
            return
        
        # Add delay in slow mode before API calls
        if slow_mode:
            time.sleep(3)
        
        # Get mechanism and activity data
        mechanisms = importer.get_compound_mechanisms(chembl_id)
        
        # Additional delay between API calls in slow mode
        if slow_mode:
            time.sleep(2)
            
        activities = importer.get_compound_activities(chembl_id)
        
        if not mechanisms:
            self.stdout.write(f"[!] No mechanisms found for {chembl_id}")
            return
        
        # Process each mechanism
        interactions_created = 0
        for mechanism_data in mechanisms:
            if self.process_mechanism(importer, compound, mechanism_data, activities, slow_mode):
                interactions_created += 1
                # Small delay between mechanism processing in slow mode
                if slow_mode and interactions_created > 0:
                    time.sleep(1)
        
        self.stdout.write(f"[✓] Created {interactions_created} interactions for {compound.name}")
    
    def _normalize_compound_name(self, name: str) -> str:
        """Normalize compound name to proper capitalization."""
        if not name:
            return name
        
        # Handle special cases and acronyms that should stay uppercase
        special_cases = {
            'ATP': 'ATP',
            'ADP': 'ADP', 
            'DNA': 'DNA',
            'RNA': 'RNA',
            'GABA': 'GABA',
            'NADH': 'NADH',
            'NADPH': 'NADPH',
            'GTP': 'GTP',
            'GDP': 'GDP',
            'cAMP': 'cAMP',
            'cGMP': 'cGMP',
            'LSD': 'LSD',
            'MDMA': 'MDMA',
            'DMT': 'DMT',
        }
        
        # Check if it's a special case (exact match)
        if name.upper() in [key.upper() for key in special_cases.keys()]:
            for key, value in special_cases.items():
                if name.upper() == key.upper():
                    return value
        
        # Check if it looks like a compound code (contains numbers and/or hyphens in specific patterns)
        # e.g., AF710b, TAK-653, VK5211
        import re
        if re.match(r'^[A-Z]{1,5}[\d-]+[a-z]*$', name, re.IGNORECASE) or re.match(r'^[A-Z]{2,5}-\d+$', name, re.IGNORECASE):
            # Preserve compound codes as-is but ensure consistent capitalization
            # Keep letters uppercase and numbers/symbols as-is
            result = ""
            for i, char in enumerate(name):
                if char.isalpha():
                    # For compound codes, typically keep letters uppercase except for suffixes
                    if i > 0 and name[i-1].isdigit() and char.islower():
                        result += char.lower()  # Keep lowercase suffixes like 'b' in AF710b
                    else:
                        result += char.upper()
                else:
                    result += char
            return result
        
        # For regular drug names, capitalize first letter and lowercase the rest
        # But preserve capitalization after spaces, hyphens, and parentheses
        normalized = ""
        capitalize_next = True
        
        for char in name:
            if char in ' -()[]':
                normalized += char
                capitalize_next = True
            elif capitalize_next:
                normalized += char.upper()
                capitalize_next = False
            else:
                normalized += char.lower()
        
        return normalized

    def get_or_create_compound(self, importer: ChEMBLImporter, chembl_id: str, slow_mode: bool = False, update_existing: bool = False, match_by_name: bool = False) -> Optional[Compound]:
        """Get existing compound or create new one from ChEMBL data."""
        # Try to find existing compound by ChEMBL ID first
        compound = Compound.objects.filter(chembl_id=chembl_id).first()
        
        if compound and not update_existing:
            self.stdout.write(f"  [i] Found existing compound: {compound.name}")
            return compound
        
        # Fetch compound data from ChEMBL
        try:
            url = f"{importer.BASE_URL}/molecule/{chembl_id}.json"
            data = importer.fetch_with_retry(url)
            
            if not data:
                return None
            
            molecule = data
            
            # Extract compound information
            name = molecule.get('pref_name', f"Compound {chembl_id}")
            if not name or name == 'null':
                # Try synonyms
                synonyms = molecule.get('molecule_synonyms', [])
                if synonyms:
                    name = synonyms[0].get('molecule_synonym', f"Compound {chembl_id}")
                else:
                    name = f"Compound {chembl_id}"
            
            # Normalize compound name to proper capitalization
            name = self._normalize_compound_name(name)
            
            # If no compound found by ChEMBL ID and match_by_name is enabled, try name matching
            if not compound and match_by_name:
                # Try to match by name or aliases
                potential_matches = Compound.objects.filter(
                    Q(name__iexact=name) |
                    Q(aliases__icontains=name)
                ).filter(chembl_id__isnull=True)
                
                if potential_matches.exists():
                    compound = potential_matches.first()
                    self.stdout.write(f"  [i] Found compound by name match: {compound.name} → will update with ChEMBL data")
            
            # Get SMILES structure if available
            structure = molecule.get('molecule_structures', {})
            smiles = ''
            if structure:
                smiles = structure.get('canonical_smiles', '')
            
            # Build comprehensive description
            description = self._build_enhanced_description(molecule, chembl_id, importer)
            
            # Get aliases from synonyms
            aliases = []
            synonyms = molecule.get('molecule_synonyms', [])
            for syn in synonyms[:5]:  # Limit to first 5 synonyms
                synonym_name = syn.get('molecule_synonym', '')
                if synonym_name and synonym_name != name:
                    aliases.append(synonym_name)
            aliases_str = ', '.join(aliases) if aliases else ''
            
            if compound:
                # Update existing compound (preserving original name)
                updated_fields = []
                
                # Note: compound.name is intentionally NOT updated to preserve original naming
                
                if update_existing or not compound.chembl_id:
                    compound.chembl_id = chembl_id
                    updated_fields.append('ChEMBL ID')
                
                if update_existing or not compound.description or 'Imported from ChEMBL' in compound.description:
                    compound.description = description
                    updated_fields.append('description')
                
                if update_existing and smiles and (not compound.smiles or compound.smiles != smiles):
                    compound.smiles = smiles
                    updated_fields.append('SMILES')
                
                if update_existing and aliases_str and (not compound.aliases or compound.aliases != aliases_str):
                    compound.aliases = aliases_str
                    updated_fields.append('aliases')
                
                compound.save()
                
                # Update categories and mechanisms
                if update_existing or not compound.categories.exists():
                    self._add_compound_categories(compound, molecule, importer)
                    updated_fields.append('categories')
                
                if update_existing or not compound.mechanism_of_action.exists():
                    self._add_compound_mechanisms(compound, chembl_id, importer, slow_mode)
                    updated_fields.append('mechanisms')
                
                self.stdout.write(f"  [✓] Updated compound: {compound.name} ({', '.join(updated_fields)})")
                
            else:
                # Create new compound
                compound, created = Compound.objects.get_or_create(
                    chembl_id=chembl_id,
                    defaults={
                        'name': name,
                        'description': description,
                        'smiles': smiles,
                        'aliases': aliases_str
                    }
                )
                
                if created:
                    # Add categories and mechanisms for new compounds
                    self._add_compound_categories(compound, molecule, importer)
                    self._add_compound_mechanisms(compound, chembl_id, importer, slow_mode)
                    self.stdout.write(f"  [✓] Created compound: {compound.name} ({chembl_id})")
                else:
                    self.stdout.write(f"  [i] Found existing compound: {compound.name}")
            
            # Add small delay in slow mode
            if slow_mode:
                time.sleep(1)
            
            return compound
            
        except Exception as e:
            self.stdout.write(f"  [✗] Error fetching compound {chembl_id}: {e}")
            return None
    
    def _build_enhanced_description(self, molecule: Dict, chembl_id: str, importer: ChEMBLImporter) -> str:
        """Build enhanced description from molecule data."""
        description_parts = []
        
        # Add primary name and common names if different
        name = molecule.get('pref_name', f"Compound {chembl_id}")
        if name != molecule.get('pref_name', ''):
            description_parts.append(f"Also known as {molecule.get('pref_name', '')}")
        
        # Add molecule type/classification in plain language
        molecule_type = molecule.get('molecule_type', '').lower()
        if molecule_type:
            if 'small molecule' in molecule_type:
                description_parts.append("A small molecule compound")
            elif 'protein' in molecule_type:
                description_parts.append("A protein-based therapeutic")
            elif 'antibody' in molecule_type:
                description_parts.append("An antibody-based treatment")
            elif 'peptide' in molecule_type:
                description_parts.append("A peptide compound")
            else:
                description_parts.append(f"A {molecule_type} compound")
        
        # Add therapeutic context
        therapeutic_flag = molecule.get('therapeutic_flag')
        if therapeutic_flag:
            description_parts.append("used for therapeutic purposes")
        
        # Add drug-like properties context
        props = molecule.get('molecule_properties', {})
        if props:
            mw = props.get('mw_freebase')
            if isinstance(mw, (int, float)) and mw > 0:
                if mw < 300:
                    description_parts.append("with relatively low molecular weight")
                elif mw > 800:
                    description_parts.append("with high molecular weight")
            
            alogp = props.get('alogp')
            if isinstance(alogp, (int, float)):
                if alogp > 3:
                    description_parts.append("with high lipophilicity")
                elif alogp < 0:
                    description_parts.append("with high water solubility")
        
        # Add structural information if interesting
        structure_type = molecule.get('structure_type', '').lower()
        if 'natural' in structure_type:
            description_parts.append("derived from natural sources")
        
        # Get mechanism summary from available data to add context
        mechanism_summary = self._get_mechanism_summary(chembl_id, importer)
        if mechanism_summary:
            description_parts.append(f"Acts primarily as {mechanism_summary}")
        
        # Construct final description
        if description_parts:
            description = ". ".join([part.capitalize() if i == 0 else part for i, part in enumerate(description_parts)]) + "."
        else:
            description = f"A compound with ChEMBL identifier {chembl_id}."
        
        # Add technical details as secondary information
        tech_details = []
        if props.get('molecular_formula'):
            tech_details.append(f"Formula: {props['molecular_formula']}")
        if isinstance(props.get('mw_freebase'), (int, float)):
            tech_details.append(f"MW: {props['mw_freebase']:.1f}")
        
        if tech_details:
            description += f" {', '.join(tech_details)}."
        
        return description
    
    def _add_compound_categories(self, compound: Compound, molecule_data: Dict, importer: ChEMBLImporter = None):
        """Add categories to compound based on ChEMBL classification and drug indications."""
        from compounds.models import CompoundCategories
        
        try:
            categories_to_add = []
            
            # Add category based on molecule type
            molecule_type = molecule_data.get('molecule_type', '').lower()
            if molecule_type:
                if molecule_type in ['small molecule', 'synthetic small molecule']:
                    categories_to_add.append('Small Molecule')
                elif 'protein' in molecule_type:
                    categories_to_add.append('Protein')
                elif 'antibody' in molecule_type:
                    categories_to_add.append('Antibody')
                elif 'peptide' in molecule_type:
                    categories_to_add.append('Peptide')
                else:
                    categories_to_add.append('Other')
            
            # Add therapeutic category if flagged
            if molecule_data.get('therapeutic_flag'):
                categories_to_add.append('Therapeutic')
            
            # Add categories based on properties
            props = molecule_data.get('molecule_properties', {})
            if props:
                mw = props.get('mw_freebase', 0)
                if isinstance(mw, (int, float)) and mw > 0:
                    if mw < 500:
                        categories_to_add.append('Drug-like')
                    elif mw > 1000:
                        categories_to_add.append('Large Molecule')
            
            # Add natural product category if indicated
            structure_type = molecule_data.get('structure_type', '').lower()
            if 'natural' in structure_type:
                categories_to_add.append('Natural Product')
            
            # Add drug indications as categories (Top 3)
            if importer and compound.chembl_id:
                indications = importer.get_drug_indications(compound.chembl_id)
                for indication_data in indications:
                    # Get indication name from available fields
                    indication = (
                        indication_data.get('efo_term', '') or
                        indication_data.get('mesh_heading', '') or
                        indication_data.get('indication', '')
                    )
                    
                    if indication:
                        # Clean and format indication name
                        category_name = self._format_indication_category(indication)
                        if category_name:
                            categories_to_add.append(category_name)
                            phase = indication_data.get('max_phase_for_ind', 'N/A')
                            self.stdout.write(f"    [+] Found indication: {indication} → {category_name} (Phase {phase})")
            
            # Add drug families from ATC classifications
            if importer and compound.chembl_id:
                atc_codes = importer.get_atc_classifications(compound.chembl_id)
                if atc_codes:
                    drug_families = importer.get_drug_families_from_atc(atc_codes)
                    for family in drug_families:
                        categories_to_add.append(family)
                        self.stdout.write(f"    [+] Found drug family: {family}")
                else:
                    self.stdout.write(f"    [i] No ATC classifications found for {compound.chembl_id}")
            
            # Create and add categories
            for cat_name in set(categories_to_add):  # Remove duplicates
                category, created = CompoundCategories.objects.get_or_create(
                    name=cat_name,
                    defaults={'description': f'Auto-generated category from ChEMBL import'}
                )
                compound.categories.add(category)
                if created:
                    self.stdout.write(f"    [+] Created category: {cat_name}")
                else:
                    self.stdout.write(f"    [+] Added to category: {cat_name}")
                    
        except Exception as e:
            self.stdout.write(f"    [!] Error adding categories: {e}")
    
    def _format_indication_category(self, indication: str) -> str:
        """Format indication text into a clean category name."""
        if not indication:
            return ""
        
        # Clean up the indication text
        indication = indication.strip()
        
        # Skip very generic or vague indications
        skip_terms = [
            'unspecified', 'not specified', 'other', 'unknown', 'various',
            'multiple', 'general', 'miscellaneous', 'undefined'
        ]
        
        if any(term in indication.lower() for term in skip_terms):
            return ""
        
        # Common indication mappings to cleaner category names
        indication_mappings = {
            # Mental Health
            'depression': 'Antidepressant',
            'depressive': 'Antidepressant', 
            'anxiety': 'Anxiolytic',
            'schizophrenia': 'Antipsychotic',
            'bipolar': 'Mood Stabilizer',
            'adhd': 'ADHD Treatment',
            'attention deficit': 'ADHD Treatment',
            
            # Pain & Inflammation
            'pain': 'Analgesic',
            'analgesic': 'Analgesic',
            'inflammation': 'Anti-inflammatory',
            'arthritis': 'Anti-inflammatory',
            'fever': 'Antipyretic',
            
            # Cardiovascular
            'hypertension': 'Antihypertensive',
            'blood pressure': 'Antihypertensive',
            'heart': 'Cardiovascular',
            'cardiac': 'Cardiovascular',
            'arrhythmia': 'Antiarrhythmic',
            
            # Neurological
            'seizure': 'Antiepileptic',
            'epilepsy': 'Antiepileptic',
            'parkinson': 'Antiparkinsonian',
            'alzheimer': 'Dementia Treatment',
            'migraine': 'Antimigraine',
            
            # Infectious Disease
            'infection': 'Antimicrobial',
            'bacterial': 'Antibiotic',
            'viral': 'Antiviral',
            'fungal': 'Antifungal',
            
            # Cancer
            'cancer': 'Anticancer',
            'tumor': 'Anticancer',
            'oncology': 'Anticancer',
            'leukemia': 'Anticancer',
            'lymphoma': 'Anticancer',
            
            # Metabolic
            'diabetes': 'Antidiabetic',
            'obesity': 'Weight Management',
            'cholesterol': 'Lipid-lowering',
            
            # Respiratory
            'asthma': 'Bronchodilator',
            'copd': 'Respiratory',
            'allergy': 'Antihistamine',
            
            # Gastrointestinal
            'ulcer': 'Gastrointestinal',
            'gastric': 'Gastrointestinal',
            'nausea': 'Antiemetic',
        }
        
        # Check for mapping matches
        indication_lower = indication.lower()
        for key, category in indication_mappings.items():
            if key in indication_lower:
                return category
        
        # If no specific mapping, use the indication as-is but clean it up
        # Capitalize properly and limit length
        clean_indication = ' '.join(word.capitalize() for word in indication.split())
        
        # Limit length and add "Treatment" if it's a condition
        if len(clean_indication) > 30:
            clean_indication = clean_indication[:27] + "..."
        
        # Add "Treatment" suffix for conditions that don't already have action words
        action_words = ['treatment', 'therapy', 'medication', 'drug', 'agent', 'inhibitor', 'blocker']
        if not any(word in clean_indication.lower() for word in action_words):
            clean_indication += " Treatment"
        
        return clean_indication
    
    def _add_compound_mechanisms(self, compound: Compound, chembl_id: str, importer: ChEMBLImporter, slow_mode: bool = False):
        """Add mechanisms of action from ChEMBL mechanism and activity data."""
        from compounds.models import CompoundMechanismOfAction
        
        try:
            # Get comprehensive mechanism data (explicit + high-affinity targets)
            mechanisms = importer.get_compound_mechanisms(chembl_id)
            
            if not mechanisms:
                self.stdout.write(f"[!] No mechanisms found for {chembl_id}")
                return
            
            if slow_mode:
                time.sleep(1)
            
            self.stdout.write(f"    [→] Found {len(mechanisms)} potential mechanisms")
            
            added_count = 0
            for i, mechanism_data in enumerate(mechanisms):
                target_chembl_id = mechanism_data.get('target_chembl_id')
                if not target_chembl_id:
                    continue
                
                # Get or create target
                target = self.get_or_create_target(importer, target_chembl_id, slow_mode)
                if not target:
                    continue
                
                # Get mechanism details
                mechanism_raw = mechanism_data.get('mechanism_of_action', '')
                source = mechanism_data.get('source', 'unknown')
                priority = mechanism_data.get('priority', 3)
                affinity_score = mechanism_data.get('affinity_score', 0)
                
                # For activity-derived mechanisms, create more descriptive mechanism text
                if source == 'activity' and affinity_score > 0:
                    if affinity_score >= 8.0:
                        potency_desc = "very high affinity"
                    elif affinity_score >= 7.0:
                        potency_desc = "high affinity"
                    elif affinity_score >= 6.0:
                        potency_desc = "moderate affinity"
                    else:
                        potency_desc = "low affinity"
                    mechanism_raw = f"{potency_desc} target interaction"
                
                # Normalize mechanism terms
                mechanism_normalized = importer.normalize_mechanism(mechanism_raw)
                
                # Map to interaction types
                interaction_type = self._map_mechanism_to_interaction_type(mechanism_normalized)
                
                # Create detailed description
                if source == 'mechanism':
                    description = f"{mechanism_raw} (ChEMBL mechanism data)"
                elif source == 'activity':
                    description = f"{mechanism_raw} (pActivity: {affinity_score:.1f}, from ChEMBL activity data)"
                else:
                    description = mechanism_raw
                
                # Create mechanism of action
                moa, created = CompoundMechanismOfAction.objects.get_or_create(
                    target_name=target,
                    target_interaction=interaction_type,
                    defaults={
                        'target_type': target.target_type,
                        'description': description
                    }
                )
                
                # Add to compound
                compound.mechanism_of_action.add(moa)
                added_count += 1
                
                # Show priority and source info
                priority_emoji = "🎯" if priority == 1 else "📊" if priority == 2 else "📋"
                affinity_text = f" (pAct: {affinity_score:.1f})" if affinity_score > 0 else ""
                
                action = "Created" if created else "Added existing"
                self.stdout.write(f"    {priority_emoji} {action} mechanism: {target.name} ({interaction_type}){affinity_text}")
                
                if slow_mode and created:
                    time.sleep(0.5)
            
            self.stdout.write(f"    [✓] Added {added_count} mechanisms to {compound.name}")
                    
        except Exception as e:
            self.stdout.write(f"    [!] Error adding mechanisms: {e}")
            import traceback
            traceback.print_exc()
    
    def _map_mechanism_to_interaction_type(self, mechanism: str) -> str:
        """Map normalized mechanism to interaction type choices."""
        mechanism_lower = mechanism.lower()
        
        # Map common mechanisms to interaction types
        if 'agonist' in mechanism_lower:
            if 'partial' in mechanism_lower:
                return 'partial_agonist'
            elif 'inverse' in mechanism_lower:
                return 'inverse_agonist'
            else:
                return 'agonist'
        elif 'antagonist' in mechanism_lower:
            return 'antagonist'
        elif 'inhibitor' in mechanism_lower:
            return 'inhibitor'
        elif 'activator' in mechanism_lower:
            return 'activator'
        elif 'modulator' in mechanism_lower:
            if 'positive' in mechanism_lower or 'pam' in mechanism_lower:
                return 'pam'
            elif 'negative' in mechanism_lower or 'nam' in mechanism_lower:
                return 'nam'
            else:
                return 'binder'  # Generic modulator
        elif 'binder' in mechanism_lower:
            return 'binder'
        elif 'upregulat' in mechanism_lower:
            return 'upregulator'
        elif 'downregulat' in mechanism_lower:
            return 'downregulator'
        else:
            return 'unknown'
    
    def find_compound(self, chembl_id: str) -> Optional[Compound]:
        """Find compound by ChEMBL ID or name."""
        # Try ChEMBL ID first
        compound = Compound.objects.filter(chembl_id=chembl_id).first()
        if compound:
            return compound
        
        # Try to find by name (requires ChEMBL lookup)
        # This would need additional API call to get compound name
        return None
    
    def process_mechanism(self, importer: ChEMBLImporter, compound: Compound, 
                         mechanism_data: Dict, activities: List[Dict], slow_mode: bool = False) -> bool:
        """Process a single mechanism and create interaction."""
        target_chembl_id = mechanism_data.get('target_chembl_id')
        if not target_chembl_id:
            return False
        
        # Get or create target (with potential API call)
        target = self.get_or_create_target(importer, target_chembl_id, slow_mode)
        if not target:
            return False
        
        # Normalize mechanism
        mechanism_raw = mechanism_data.get('mechanism_of_action', '')
        mechanism = importer.normalize_mechanism(mechanism_raw)
        
        # Get or create structured action type
        structured_action_type = importer.get_or_create_action_type(mechanism_raw)
        
        # Calculate affinity level
        affinity_level = importer.calculate_affinity_level(activities)
        
        # Create or update interaction
        interaction, created = CompoundTargetInteraction.objects.get_or_create(
            compound=compound,
            target=target,
            defaults={
                'mechanism': mechanism,
                'structured_action_type': structured_action_type,
                'affinity_level': affinity_level,
                'notes': mechanism_raw,
                'source': 'ChEMBL'
            }
        )
        
        if not created and interaction.source == 'ChEMBL':
            # Update existing ChEMBL interaction
            interaction.mechanism = mechanism
            interaction.structured_action_type = structured_action_type
            interaction.affinity_level = affinity_level
            interaction.notes = mechanism_raw
            interaction.save()
            interaction.save()
        
        action = "Created" if created else "Updated"
        self.stdout.write(f"  [✓] {action} interaction: {compound.name} → {target.name} ({mechanism})")
        
        return True
    
    def get_or_create_target(self, importer: ChEMBLImporter, target_chembl_id: str, slow_mode: bool = False) -> Optional[Target]:
        """Get or create target from ChEMBL data."""
        # Check if target already exists by ChEMBL ID
        target = Target.objects.filter(chembl_id=target_chembl_id).first()
        if target:
            return target
        
        # Add delay before API call in slow mode
        if slow_mode:
            time.sleep(2)
        
        # Fetch target details from ChEMBL
        target_data = importer.get_target_details(target_chembl_id)
        if not target_data:
            return None
        
        # Extract target information
        target_name = target_data.get('pref_name', 'Unknown')
        target_type = target_data.get('target_type', 'unknown').lower()
        description = target_data.get('description', '')
        organism = target_data.get('organism', '')
        
        # Get or create structured target type
        structured_target_type = importer.get_or_create_target_type(target_data.get('target_type', 'unknown'))
        
        # Check if target exists by name (without ChEMBL ID)
        existing_target = Target.objects.filter(name=target_name, chembl_id__isnull=True).first()
        if existing_target:
            # Update existing target with ChEMBL data
            existing_target.chembl_id = target_chembl_id
            existing_target.target_type = target_type
            existing_target.structured_target_type = structured_target_type
            if not existing_target.description:
                existing_target.description = description
            existing_target.save()
            self.stdout.write(f"  [✓] Updated existing target with ChEMBL data: {existing_target.name}")
            return existing_target
        
        # Create new target with unique name handling
        try:
            target, created = Target.objects.get_or_create(
                chembl_id=target_chembl_id,
                defaults={
                    'name': target_name,
                    'target_type': target_type,
                    'type': target_type,  # For backward compatibility
                    'structured_target_type': structured_target_type,
                    'description': description,
                    'organism': organism
                }
            )
            
            if not created:
                # Target exists, just return it
                return target
            
            # If name conflicts, make it unique
            if Target.objects.filter(name=target_name).exclude(id=target.id).exists():
                unique_name = f"{target_name} ({target_chembl_id})"
                target.name = unique_name
                target.save()
                self.stdout.write(f"  [→] Created target with unique name: {unique_name} ({target.target_type})")
            else:
                self.stdout.write(f"  [→] Created target: {target.name} ({target.target_type})")
                
        except Exception as e:
            self.stdout.write(f"  [✗] Error creating target {target_chembl_id}: {e}")
            # Try to find existing target by name as fallback
            fallback_target = Target.objects.filter(name=target_name).first()
            if fallback_target:
                self.stdout.write(f"  [i] Using existing target: {fallback_target.name}")
                return fallback_target
            return None
        
        return target
    
    def create_compound_interactions(self):
        """Create compound-to-compound interactions based on shared targets."""
        self.stdout.write("[→] Analyzing compound pairs with shared targets...")
        
        # Get all targets with multiple compounds
        targets_with_compounds = {}
        for interaction in CompoundTargetInteraction.objects.select_related('compound', 'target'):
            target_id = interaction.target_id
            if target_id not in targets_with_compounds:
                targets_with_compounds[target_id] = []
            targets_with_compounds[target_id].append(interaction)
        
        created_count = 0
        
        for target_id, interactions in targets_with_compounds.items():
            if len(interactions) < 2:
                continue
            
            target = interactions[0].target
            
            # Create pairs of compounds sharing this target
            for i in range(len(interactions)):
                for j in range(i + 1, len(interactions)):
                    interaction1 = interactions[i]
                    interaction2 = interactions[j]
                    
                    if self.create_compound_pair_interaction(
                        interaction1, interaction2, target
                    ):
                        created_count += 1
        
        self.stdout.write(f"[✓] Created {created_count} compound-to-compound interactions")
    
    def create_compound_pair_interaction(self, interaction1: CompoundTargetInteraction,
                                       interaction2: CompoundTargetInteraction,
                                       shared_target: Target) -> bool:
        """Create interaction between two compounds sharing a target."""
        compound1 = interaction1.compound
        compound2 = interaction2.compound
        
        # Check if interaction already exists
        existing = CompoundToCompoundTargetInteraction.objects.filter(
            Q(compound_a=compound1, compound_b=compound2) |
            Q(compound_a=compound2, compound_b=compound1)
        ).filter(target=shared_target).first()
        
        if existing:
            return False
        
        # Infer interaction type based on mechanisms
        mechanism1 = interaction1.mechanism
        mechanism2 = interaction2.mechanism
        interaction_type = self.infer_interaction_type(mechanism1, mechanism2)
        
        # Create interaction
        CompoundToCompoundTargetInteraction.objects.create(
            compound_a=compound1,
            compound_b=compound2,
            target=shared_target,
            interaction_type=interaction_type,
            description=f"{compound1.name}: {mechanism1}, {compound2.name}: {mechanism2}",
            confidence='medium',
            source='ChEMBL'
        )
        
        self.stdout.write(f"  [✓] {compound1.name} ↔ {compound2.name} → {interaction_type}")
        return True
    
    def infer_interaction_type(self, mechanism1: str, mechanism2: str) -> str:
        """Infer interaction type based on mechanisms."""
        # Both agonists
        if mechanism1 == 'agonist' and mechanism2 == 'agonist':
            return 'synergistic'
        
        # Agonist + Antagonist
        if (mechanism1 == 'agonist' and mechanism2 == 'antagonist') or \
           (mechanism1 == 'antagonist' and mechanism2 == 'agonist'):
            return 'antagonistic'
        
        # Both inhibitors
        if mechanism1 == 'inhibitor' and mechanism2 == 'inhibitor':
            return 'synergistic'
        
        # Substrate + Inhibitor
        if (mechanism1 == 'substrate' and mechanism2 == 'inhibitor') or \
           (mechanism1 == 'inhibitor' and mechanism2 == 'substrate'):
            return 'enzyme_inhibition'
        
        # Both modulators
        if mechanism1 == 'modulator' and mechanism2 == 'modulator':
            return 'synergistic'
        
        # Both blockers
        if mechanism1 == 'blocker' and mechanism2 == 'blocker':
            return 'synergistic'
        
        # Different mechanisms - competitive
        if mechanism1 != mechanism2 and mechanism1 != 'unknown' and mechanism2 != 'unknown':
            return 'competitive'
        
        return 'unknown'
    
    def _get_mechanism_summary(self, chembl_id: str, importer: ChEMBLImporter) -> str:
        """Get a brief summary of the compound's primary mechanism for description."""
        try:
            mechanisms = importer.get_compound_mechanisms(chembl_id)
            if not mechanisms:
                return ""
            
            # Count mechanism types to find the most common
            mechanism_counts = {}
            target_types = {}
            
            for mechanism_data in mechanisms:
                mechanism = mechanism_data.get('mechanism_of_action', '').lower()
                normalized = importer.normalize_mechanism(mechanism)
                
                if normalized not in mechanism_counts:
                    mechanism_counts[normalized] = 0
                mechanism_counts[normalized] += 1
                
                # Track target types too
                target_chembl_id = mechanism_data.get('target_chembl_id')
                if target_chembl_id:
                    target_data = importer.get_target_details(target_chembl_id)
                    if target_data:
                        target_type = target_data.get('target_type', '').lower()
                        if target_type not in target_types:
                            target_types[target_type] = 0
                        target_types[target_type] += 1
            
            # Get most common mechanism and target type
            primary_mechanism = max(mechanism_counts.keys()) if mechanism_counts else ""
            primary_target_type = max(target_types.keys()) if target_types else ""
            
            # Create readable summary
            if primary_mechanism and primary_target_type:
                if primary_mechanism in ['agonist', 'partial_agonist']:
                    return f"an {primary_target_type} activator"
                elif primary_mechanism == 'antagonist':
                    return f"an {primary_target_type} blocker"
                elif primary_mechanism == 'inhibitor':
                    if primary_target_type == 'enzyme':
                        return f"an enzyme inhibitor"
                    else:
                        return f"a {primary_target_type} inhibitor"
                elif primary_mechanism in ['modulator', 'pam', 'nam']:
                    return f"a {primary_target_type} modulator"
                elif primary_mechanism in ['upregulator', 'activator']:
                    return f"a {primary_target_type} enhancer"
                elif primary_mechanism == 'downregulator':
                    return f"a {primary_target_type} reducer"
                else:
                    return f"a {primary_target_type} targeting compound"
            
            return ""
            
        except Exception:
            # Don't let mechanism summary errors break the import
            return ""
    
    def normalize_existing_compound_names(self):
        """Normalize all existing compound names to proper capitalization."""
        self.stdout.write(self.style.SUCCESS('[🔧] Normalizing existing compound names...'))
        
        compounds = Compound.objects.all().order_by('name')
        updated_count = 0
        
        for compound in compounds:
            original_name = compound.name
            normalized_name = self._normalize_compound_name(original_name)
            
            if original_name != normalized_name:
                compound.name = normalized_name
                compound.save(update_fields=['name'])
                updated_count += 1
                self.stdout.write(f"  [✓] '{original_name}' → '{normalized_name}'")
            else:
                self.stdout.write(f"  [i] '{original_name}' (no change needed)")
        
        self.stdout.write(self.style.SUCCESS(f'[✓] Normalization complete! Updated {updated_count} out of {compounds.count()} compounds.'))
