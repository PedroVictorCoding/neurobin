#!/usr/bin/env python
"""
Comprehensive Neurobin Data Population Script
Uses multiple APIs and data sources to populate all models with real data.

Data Sources:
- Reactome API for pathways and interactions
- ChEMBL API for compound and target data  
- PubChem API for chemical structures
- UniProt API for protein data
- DrugBank (if available) for drug information
- KEGG API for pathway data

Usage:
    python populate_all_data.py --full --no-limits
"""

import os
import sys
import django
from django.db.models import Count
import requests
import json
import time
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from urllib.parse import quote, urljoin
from typing import Dict, List, Optional, Tuple, Any
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
from django.utils import timezone
from itertools import combinations

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from compounds.models import (
    ActionType, TargetType, CompoundCategories, Target, 
    CompoundMechanismOfAction, Compound, EffectWindow, CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction
)
from research.models import (
    ResearchSnippet, SnippetTag, SnippetTagging,
    SnippetComment, UserRole, ResearchSettings
)
from accounts.models import UserProfile

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_population.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class APIClient:
    """Base class for API clients with rate limiting and error handling"""
    
    def __init__(self, base_url: str, rate_limit: float = 0.1):
        self.base_url = base_url
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Neurobin-DataPopulation/1.0 (research purposes)',
            'Accept': 'application/json'
        })
    
    def get(self, endpoint: str, params: Optional[Dict] = None, retry_count: int = 3) -> Optional[Dict]:
        """Make GET request with retry logic and rate limiting"""
        url = urljoin(self.base_url, endpoint)
        
        for attempt in range(retry_count):
            try:
                time.sleep(self.rate_limit)
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limited
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"HTTP {response.status_code} for {url}")
                    return None
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed for {url}: {e}")
                if attempt == retry_count - 1:
                    return None
                time.sleep(2 ** attempt)
        
        return None

class ReactomeAPI(APIClient):
    """Reactome Content Service API client"""
    
    def __init__(self):
        super().__init__('https://reactome.org/ContentService/', rate_limit=0.2)
    
    def get_all_pathways(self, species: str = "9606") -> List[Dict]:
        """Get all pathways for a species (default: Homo sapiens)"""
        data = self.get(f'data/pathways/top/{species}')
        return data if data else []
    
    def get_pathway_participants(self, pathway_id: str) -> Dict:
        """Get all participants in a pathway"""
        return self.get(f'data/participants/{pathway_id}')
    
    def get_protein_pathways(self, protein_id: str) -> List[Dict]:
        """Get pathways for a protein"""
        data = self.get(f'data/pathways/low/entity/{protein_id}')
        return data if data else []
    
    def search_molecules(self, query: str) -> List[Dict]:
        """Search for molecules"""
        data = self.get('search/query', params={'query': query, 'types': 'SimpleEntity,Complex'})
        return data.get('results', []) if data else []

class ChEMBLAPI(APIClient):
    """ChEMBL REST API client"""
    
    def __init__(self):
        super().__init__('https://www.ebi.ac.uk/chembl/api/data/', rate_limit=0.1)
    
    def get_compounds(self, limit: int = 1000, offset: int = 0) -> Dict:
        """Get compounds from ChEMBL"""
        params = {
            'limit': min(limit, 1000),  # ChEMBL max limit
            'offset': offset,
            'format': 'json'
        }
        return self.get('molecule', params=params)
    
    def get_targets(self, limit: int = 1000, offset: int = 0) -> Dict:
        """Get targets from ChEMBL"""
        params = {
            'limit': min(limit, 1000),
            'offset': offset,
            'format': 'json'
        }
        return self.get('target', params=params)
    
    def get_activities(self, limit: int = 1000, offset: int = 0) -> Dict:
        """Get bioactivity data"""
        params = {
            'limit': min(limit, 1000),
            'offset': offset,
            'format': 'json'
        }
        return self.get('activity', params=params)
    
    def get_mechanisms(self, limit: int = 1000, offset: int = 0) -> Dict:
        """Get mechanism of action data"""
        params = {
            'limit': min(limit, 1000),
            'offset': offset,
            'format': 'json'
        }
        return self.get('mechanism', params=params)

    def get_molecule_details(self, chembl_id: str) -> Optional[Dict]:
        """Fetch molecule details for a specific ChEMBL ID"""
        if not chembl_id:
            return None

        return self.get('molecule', params={'molecule_chembl_id': chembl_id, 'format': 'json'})

class PubChemAPI(APIClient):
    """PubChem REST API client"""
    
    def __init__(self):
        super().__init__('https://pubchem.ncbi.nlm.nih.gov/rest/pug/', rate_limit=0.2)
    
    def get_compound_by_name(self, name: str) -> Optional[Dict]:
        """Get compound data by name"""
        endpoint = f'compound/name/{quote(name)}/JSON'
        return self.get(endpoint)
    
    def get_compound_properties(self, cid: str) -> Optional[Dict]:
        """Get compound properties"""
        endpoint = f'compound/cid/{cid}/property/MolecularFormula,MolecularWeight,InChI,InChIKey,CanonicalSMILES/JSON'
        return self.get(endpoint)

class UniProtAPI(APIClient):
    """UniProt REST API client"""
    
    def __init__(self):
        super().__init__('https://rest.uniprot.org/', rate_limit=0.1)
    
    def search_proteins(self, query: str, limit: int = 100) -> List[Dict]:
        """Search proteins"""
        params = {
            'query': query,
            'format': 'json',
            'size': min(limit, 500)
        }
        data = self.get('uniprotkb/search', params=params)
        return data.get('results', []) if data else []

class PubMedAPI(APIClient):
    """PubMed API client using NCBI E-utilities"""

    def __init__(self, api_key: Optional[str] = None, email: str = 'neurobin@neurobin.com'):
        super().__init__('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/', rate_limit=0.25)
        self.default_params = {'email': email}
        if api_key:
            self.default_params['api_key'] = api_key

    def search(self, term: str, retmax: int = 5) -> Dict:
        """Search PubMed for a given term"""
        params = {
            **self.default_params,
            'db': 'pubmed',
            'term': term,
            'retmode': 'json',
            'retmax': min(retmax, 20)
        }
        return self.get('esearch.fcgi', params=params) or {}

    def fetch_summaries(self, ids: List[str]) -> List[Dict]:
        """Fetch summaries for a list of PubMed IDs"""
        if not ids:
            return []

        params = {
            **self.default_params,
            'db': 'pubmed',
            'id': ','.join(ids),
            'retmode': 'json'
        }

        data = self.get('esummary.fcgi', params=params)

        if not data:
            return []

        result = data.get('result', {})
        summaries = []
        for uid in result.get('uids', []):
            entry = result.get(uid, {})
            summaries.append({
                'uid': uid,
                'title': entry.get('title', '').strip(),
                'summary': entry.get('summary', entry.get('title', 'Publication summary unavailable')),
                'doi': entry.get('elocationid', '').strip(),
                'pubdate': entry.get('pubdate', ''),
                'source': entry.get('source', ''),
            })

        return summaries

class DataPopulator:
    """Main data population class"""

    ACTIVATING_MECHANISMS = {
        'agonist', 'partial_agonist', 'inverse_agonist', 'activator',
        'inducer', 'substrate', 'opener', 'pam', 'upregulator'
    }

    INHIBITING_MECHANISMS = {
        'antagonist', 'inhibitor', 'blocker', 'nam', 'downregulator'
    }

    MODULATING_MECHANISMS = {
        'modulator', 'binder'
    }
    
    def __init__(self, no_limits: bool = False, allow_dummy_research: bool = False):
        self.no_limits = no_limits
        self.allow_dummy_research = allow_dummy_research
        self.reactome = ReactomeAPI()
        self.chembl = ChEMBLAPI()
        self.pubchem = PubChemAPI()
        self.uniprot = UniProtAPI()
        self.pubmed = PubMedAPI()
        
        # Ensure superuser exists
        self.admin_user = self.get_or_create_admin_user()
        
        logger.info(f"Data populator initialized (no_limits={no_limits})")
    
    def get_or_create_admin_user(self) -> User:
        """Get or create admin user for data creation"""
        user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@neurobin.com',
                'is_staff': True,
                'is_superuser': True,
                'first_name': 'Admin',
                'last_name': 'User'
            }
        )
        if created:
            user.set_password('admin123')
            user.save()
            logger.info("Created admin user")
        return user
    
    def populate_action_types(self):
        """Populate action types with comprehensive data"""
        logger.info("Populating action types...")
        
        action_types = [
            # Receptor interactions
            ('agonist', 'Agonist', 'Binds to and activates a receptor', 'activation'),
            ('partial_agonist', 'Partial Agonist', 'Binds to receptor with submaximal activation', 'activation'),
            ('antagonist', 'Antagonist', 'Binds to receptor without activation, blocks agonists', 'inhibition'),
            ('inverse_agonist', 'Inverse Agonist', 'Binds to receptor and reduces constitutive activity', 'inhibition'),
            ('allosteric_modulator', 'Allosteric Modulator', 'Binds to allosteric site to modulate receptor', 'modulation'),
            ('positive_allosteric_modulator', 'Positive Allosteric Modulator', 'Enhances receptor response to agonists', 'modulation'),
            ('negative_allosteric_modulator', 'Negative Allosteric Modulator', 'Reduces receptor response to agonists', 'modulation'),
            
            # Enzyme interactions
            ('inhibitor', 'Inhibitor', 'Reduces or blocks enzyme activity', 'inhibition'),
            ('competitive_inhibitor', 'Competitive Inhibitor', 'Competes with substrate for active site', 'inhibition'),
            ('non_competitive_inhibitor', 'Non-competitive Inhibitor', 'Binds to allosteric site to reduce activity', 'inhibition'),
            ('uncompetitive_inhibitor', 'Uncompetitive Inhibitor', 'Binds only to enzyme-substrate complex', 'inhibition'),
            ('irreversible_inhibitor', 'Irreversible Inhibitor', 'Permanently modifies enzyme', 'inhibition'),
            ('activator', 'Activator', 'Increases enzyme activity', 'activation'),
            ('inducer', 'Inducer', 'Increases expression of enzyme', 'activation'),
            
            # Transporter interactions
            ('substrate', 'Substrate', 'Transported by the protein', 'transport'),
            ('blocker', 'Blocker', 'Blocks transporter function', 'inhibition'),
            ('uptake_inhibitor', 'Uptake Inhibitor', 'Prevents reuptake via transporter', 'inhibition'),
            
            # Ion channel interactions
            ('opener', 'Channel Opener', 'Increases channel opening probability', 'activation'),
            ('closer', 'Channel Closer', 'Decreases channel opening probability', 'inhibition'),
            ('modulator', 'Modulator', 'Alters channel properties', 'modulation'),
            
            # General interactions
            ('binding_agent', 'Binding Agent', 'Binds to target without functional effect', 'binding'),
            ('cofactor', 'Cofactor', 'Required for protein function', 'activation'),
            ('chelator', 'Chelator', 'Binds metal ions', 'binding'),
            ('stabilizer', 'Stabilizer', 'Stabilizes protein structure/function', 'modulation'),
            ('destabilizer', 'Destabilizer', 'Destabilizes protein structure/function', 'modulation'),
            
            # Signaling
            ('signaling_molecule', 'Signaling Molecule', 'Participates in cell signaling', 'signaling'),
            ('second_messenger', 'Second Messenger', 'Intracellular signaling molecule', 'signaling'),
            
            # Metabolism
            ('metabolite', 'Metabolite', 'Product of metabolic processes', 'metabolism'),
            ('precursor', 'Precursor', 'Converted to active form', 'metabolism'),
            ('prodrug', 'Prodrug', 'Inactive until metabolized', 'metabolism'),
        ]
        
        created_count = 0
        for name, display_name, description, category in action_types:
            action_type, created = ActionType.objects.get_or_create(
                name=name,
                defaults={
                    'display_name': display_name,
                    'description': description,
                    'category': category
                }
            )
            if created:
                created_count += 1
        
        logger.info(f"Created {created_count} action types")
    
    def populate_target_types(self):
        """Populate target types with comprehensive data"""
        logger.info("Populating target types...")
        
        target_types = [
            # Receptors
            ('gpcr', 'G-Protein Coupled Receptor', 'Seven-transmembrane receptors coupled to G-proteins', 'membrane'),
            ('ligand_gated_ion_channel', 'Ligand-Gated Ion Channel', 'Ion channels opened by ligand binding', 'membrane'),
            ('nuclear_receptor', 'Nuclear Receptor', 'Intracellular receptors for hormones', 'intracellular'),
            ('receptor_tyrosine_kinase', 'Receptor Tyrosine Kinase', 'Membrane receptors with kinase activity', 'membrane'),
            ('cytokine_receptor', 'Cytokine Receptor', 'Receptors for cytokines and growth factors', 'membrane'),
            
            # Enzymes
            ('kinase', 'Protein Kinase', 'Enzymes that phosphorylate proteins', 'intracellular'),
            ('phosphatase', 'Protein Phosphatase', 'Enzymes that dephosphorylate proteins', 'intracellular'),
            ('protease', 'Protease', 'Enzymes that cleave proteins', 'various'),
            ('lipase', 'Lipase', 'Enzymes that hydrolyze lipids', 'various'),
            ('oxidoreductase', 'Oxidoreductase', 'Enzymes that catalyze oxidation-reduction', 'various'),
            ('transferase', 'Transferase', 'Enzymes that transfer functional groups', 'various'),
            ('hydrolase', 'Hydrolase', 'Enzymes that catalyze hydrolysis', 'various'),
            ('lyase', 'Lyase', 'Enzymes that add/remove groups to form double bonds', 'various'),
            ('isomerase', 'Isomerase', 'Enzymes that catalyze isomerization', 'various'),
            ('ligase', 'Ligase', 'Enzymes that catalyze joining of molecules', 'various'),
            
            # Ion Channels
            ('voltage_gated_channel', 'Voltage-Gated Ion Channel', 'Ion channels opened by voltage changes', 'membrane'),
            ('calcium_channel', 'Calcium Channel', 'Channels selective for calcium ions', 'membrane'),
            ('sodium_channel', 'Sodium Channel', 'Channels selective for sodium ions', 'membrane'),
            ('potassium_channel', 'Potassium Channel', 'Channels selective for potassium ions', 'membrane'),
            ('chloride_channel', 'Chloride Channel', 'Channels selective for chloride ions', 'membrane'),
            
            # Transporters
            ('transporter', 'Transporter', 'Proteins that transport molecules across membranes', 'membrane'),
            ('abc_transporter', 'ABC Transporter', 'ATP-binding cassette transporters', 'membrane'),
            ('symporter', 'Symporter', 'Transporters that move molecules in same direction', 'membrane'),
            ('antiporter', 'Antiporter', 'Transporters that move molecules in opposite directions', 'membrane'),
            ('uniporter', 'Uniporter', 'Transporters that move single molecule type', 'membrane'),
            
            # Structural proteins
            ('structural_protein', 'Structural Protein', 'Proteins providing structural support', 'various'),
            ('cytoskeletal_protein', 'Cytoskeletal Protein', 'Proteins forming cellular skeleton', 'intracellular'),
            ('motor_protein', 'Motor Protein', 'Proteins that generate movement', 'intracellular'),
            
            # Binding proteins
            ('binding_protein', 'Binding Protein', 'Proteins that bind specific molecules', 'various'),
            ('carrier_protein', 'Carrier Protein', 'Proteins that transport molecules', 'various'),
            ('storage_protein', 'Storage Protein', 'Proteins that store molecules', 'various'),
            
            # Regulatory proteins
            ('transcription_factor', 'Transcription Factor', 'Proteins that regulate gene expression', 'intracellular'),
            ('regulatory_protein', 'Regulatory Protein', 'Proteins that regulate cellular processes', 'various'),
            ('chaperone', 'Chaperone Protein', 'Proteins that assist protein folding', 'intracellular'),
            
            # Immune system
            ('antibody', 'Antibody', 'Immunoglobulin proteins', 'secreted'),
            ('complement_protein', 'Complement Protein', 'Proteins in complement system', 'secreted'),
            ('cytokine', 'Cytokine', 'Cell signaling proteins', 'secreted'),
            
            # Others
            ('hormone', 'Hormone', 'Signaling molecules', 'secreted'),
            ('neurotransmitter_receptor', 'Neurotransmitter Receptor', 'Receptors for neurotransmitters', 'membrane'),
            ('adhesion_molecule', 'Adhesion Molecule', 'Proteins mediating cell adhesion', 'membrane'),
            ('gap_junction_protein', 'Gap Junction Protein', 'Proteins forming intercellular channels', 'membrane'),
        ]
        
        created_count = 0
        for name, display_name, description, category in target_types:
            target_type, created = TargetType.objects.get_or_create(
                name=name,
                defaults={
                    'display_name': display_name,
                    'description': description,
                    'category': category
                }
            )
            if created:
                created_count += 1
        
        logger.info(f"Created {created_count} target types")
    
    def populate_compound_categories(self):
        """Populate compound categories"""
        logger.info("Populating compound categories...")
        
        categories = [
            ('Neurotransmitters', 'Chemical messengers in the nervous system'),
            ('Psychedelics', 'Compounds that alter perception and consciousness'),
            ('Stimulants', 'Compounds that increase alertness and energy'),
            ('Depressants', 'Compounds that reduce neural activity'),
            ('Anxiolytics', 'Compounds that reduce anxiety'),
            ('Antidepressants', 'Compounds that treat depression'),
            ('Antipsychotics', 'Compounds that treat psychosis'),
            ('Nootropics', 'Compounds that enhance cognitive function'),
            ('Analgesics', 'Compounds that relieve pain'),
            ('Anticonvulsants', 'Compounds that prevent seizures'),
            ('Muscle Relaxants', 'Compounds that reduce muscle tension'),
            ('Hormones', 'Chemical messengers in the endocrine system'),
            ('Vitamins', 'Essential nutrients for proper body function'),
            ('Minerals', 'Inorganic substances essential for health'),
            ('Amino Acids', 'Building blocks of proteins'),
            ('Peptides', 'Short chains of amino acids'),
            ('Proteins', 'Large molecules made of amino acid chains'),
            ('Lipids', 'Fatty molecules including fats and oils'),
            ('Carbohydrates', 'Sugar and starch molecules'),
            ('Alkaloids', 'Nitrogen-containing plant compounds'),
            ('Terpenes', 'Aromatic compounds found in plants'),
            ('Phenethylamines', 'Class of organic compounds'),
            ('Tryptamines', 'Class of monoamine alkaloids'),
            ('Benzodiazepines', 'Class of psychoactive drugs'),
            ('Barbiturates', 'Class of depressant drugs'),
            ('Opioids', 'Compounds that act on opioid receptors'),
            ('Cannabinoids', 'Compounds that act on cannabinoid receptors'),
            ('Anticholinergics', 'Compounds that block acetylcholine'),
            ('Cholinergics', 'Compounds that mimic or enhance acetylcholine'),
            ('Adrenergics', 'Compounds that mimic or enhance adrenaline'),
            ('Dopaminergics', 'Compounds that affect dopamine systems'),
            ('Serotonergics', 'Compounds that affect serotonin systems'),
            ('GABAergics', 'Compounds that affect GABA systems'),
            ('Glutamatergics', 'Compounds that affect glutamate systems'),
            ('Antihistamines', 'Compounds that block histamine'),
            ('Antimicrobials', 'Compounds that kill or inhibit microorganisms'),
            ('Antifungals', 'Compounds that treat fungal infections'),
            ('Antivirals', 'Compounds that treat viral infections'),
            ('Antibiotics', 'Compounds that treat bacterial infections'),
            ('Anti-inflammatory', 'Compounds that reduce inflammation'),
            ('Immunosuppressants', 'Compounds that suppress immune response'),
            ('Immunostimulants', 'Compounds that enhance immune response'),
            ('Antioxidants', 'Compounds that prevent oxidative damage'),
            ('Neuroprotective', 'Compounds that protect nerve cells'),
            ('Cardioprotective', 'Compounds that protect heart tissue'),
            ('Hepatoprotective', 'Compounds that protect liver tissue'),
            ('Research Chemicals', 'Compounds used primarily for research'),
            ('Natural Products', 'Compounds derived from natural sources'),
            ('Synthetic Compounds', 'Artificially created compounds'),
            ('Prodrugs', 'Inactive compounds converted to active form'),
            ('Metabolites', 'Products of metabolic processes'),
        ]
        
        created_count = 0
        for name, description in categories:
            category, created = CompoundCategories.objects.get_or_create(
                name=name,
                defaults={'description': description}
            )
            if created:
                created_count += 1
        
        logger.info(f"Created {created_count} compound categories")
    
    def populate_targets_from_chembl(self, limit: int = None):
        """Populate targets from ChEMBL database"""
        logger.info("Populating targets from ChEMBL...")
        
        max_requests = 10 if not self.no_limits else 100
        targets_per_request = 1000
        total_created = 0
        
        for page in range(max_requests):
            offset = page * targets_per_request
            data = self.chembl.get_targets(limit=targets_per_request, offset=offset)
            
            if not data or 'targets' not in data:
                break
            
            targets = data['targets']
            if not targets:
                break
            
            for target_data in targets:
                try:
                    # Map ChEMBL target type to our target types
                    chembl_type = target_data.get('target_type', 'UNKNOWN').lower()
                    target_type_mapping = {
                        'single protein': 'protein',
                        'protein complex': 'protein',
                        'protein family': 'protein',
                        'enzyme': 'enzyme',
                        'gpcr': 'gpcr',
                        'ion channel': 'ligand_gated_ion_channel',
                        'transporter': 'transporter',
                        'kinase': 'kinase',
                        'nuclear receptor': 'nuclear_receptor',
                        'membrane receptor': 'receptor',
                        'secreted protein': 'binding_protein',
                        'structural protein': 'structural_protein',
                        'transcription factor': 'transcription_factor',
                        'unknown': 'protein',
                    }
                    
                    mapped_type = target_type_mapping.get(chembl_type, 'protein')
                    
                    # Get or create structured target type
                    structured_type = TargetType.objects.filter(name=mapped_type).first()
                    
                    # Extract target name and make it unique if needed
                    target_name = target_data.get('pref_name', 'Unknown Target')[:255]
                    chembl_id = target_data.get('target_chembl_id')
                    
                    # Skip if no ChEMBL ID (can't properly identify the target)
                    if not chembl_id:
                        continue
                    
                    # Extract gene name safely
                    gene_name = None
                    target_components = target_data.get('target_components', [])
                    if target_components and len(target_components) > 0:
                        component = target_components[0]
                        gene_name = component.get('component_synonym') or component.get('gene_name')
                        if gene_name:
                            gene_name = gene_name[:50]  # Ensure it fits the field length
                    
                    # Extract description safely
                    description = ''
                    if target_components and len(target_components) > 0:
                        description = target_components[0].get('description', '')
                        if description:
                            description = description[:1000]  # Ensure it fits the field length
                    
                    # Try to get or create by ChEMBL ID first
                    try:
                        target, created = Target.objects.get_or_create(
                            chembl_id=chembl_id,
                            defaults={
                                'name': target_name,
                                'target_type': mapped_type,
                                'type': mapped_type,  # For backward compatibility
                                'structured_target_type': structured_type,
                                'description': description,
                                'organism': target_data.get('organism', 'Homo sapiens'),
                                'gene_name': gene_name,
                            }
                        )
                    except Exception as e:
                        if 'UNIQUE constraint failed: compounds_target.name' in str(e):
                            # Handle name conflict by making the name unique
                            unique_name = f"{target_name} ({chembl_id})"
                            try:
                                target, created = Target.objects.get_or_create(
                                    chembl_id=chembl_id,
                                    defaults={
                                        'name': unique_name,
                                        'target_type': mapped_type,
                                        'type': mapped_type,
                                        'structured_target_type': structured_type,
                                        'description': description,
                                'organism': target_data.get('organism', 'Homo sapiens'),
                                'gene_name': gene_name,
                                    }
                                )
                            except Exception as e2:
                                # If still fails, try with a timestamp
                                import time
                                timestamp_name = f"{target_name} ({chembl_id}_{int(time.time())})"
                                target, created = Target.objects.get_or_create(
                                    chembl_id=chembl_id,
                                    defaults={
                                        'name': timestamp_name,
                                        'target_type': mapped_type,
                                        'type': mapped_type,
                                        'structured_target_type': structured_type,
                                        'description': description,
                                'organism': target_data.get('organism', 'Homo sapiens'),
                                'gene_name': gene_name,
                                    }
                                )
                        else:
                            # Re-raise if it's a different error
                            raise e
                    
                    # If not created and target exists, update the name if it conflicts
                    if not created:
                        # Check if there's a name conflict with a different target
                        existing_target_with_name = Target.objects.filter(name=target_name).exclude(id=target.id).first()
                        if existing_target_with_name:
                            # Update the name to make it unique
                            target.name = f"{target_name} ({chembl_id})"
                            target.save()
                    else:
                        # For newly created targets, check for name conflicts
                        existing_target_with_name = Target.objects.filter(name=target_name).exclude(id=target.id).first()
                        if existing_target_with_name:
                            # Update the name to make it unique
                            target.name = f"{target_name} ({chembl_id})"
                            target.save()
                    
                    if created:
                        total_created += 1
                        
                except Exception as e:
                    logger.error(f"Error creating target: {e}")
                    continue
            
            logger.info(f"Processed page {page + 1}, created {total_created} targets so far")
            
            if limit and total_created >= limit:
                break
        
        logger.info(f"Created {total_created} targets from ChEMBL")
    
    def populate_compounds_from_chembl(self, limit: int = None):
        """Populate compounds from ChEMBL database"""
        logger.info("Populating compounds from ChEMBL...")
        
        max_requests = 10 if not self.no_limits else 100
        compounds_per_request = 1000
        total_created = 0
        
        # Get some categories for assignment
        categories = list(CompoundCategories.objects.all()[:10])
        
        for page in range(max_requests):
            offset = page * compounds_per_request
            data = self.chembl.get_compounds(limit=compounds_per_request, offset=offset)
            
            if not data or 'molecules' not in data:
                break
            
            molecules = data['molecules']
            if not molecules:
                break
            
            chembl_ids = [
                mol_data.get('molecule_chembl_id')
                for mol_data in molecules
                if mol_data.get('molecule_chembl_id')
            ]
            existing_ids = set(
                Compound.objects.filter(chembl_id__in=chembl_ids)
                .values_list('chembl_id', flat=True)
            )
            
            for mol_data in molecules:
                try:
                    # Skip if no SMILES
                    smiles = mol_data.get('molecule_structures', {}).get('canonical_smiles') if mol_data.get('molecule_structures') else None
                    if not smiles:
                        continue
                    
                    props = mol_data.get('molecule_properties') or {}
                    
                    chembl_id = mol_data.get('molecule_chembl_id')
                    if not chembl_id or chembl_id in existing_ids:
                        continue
                    
                    # Create compound
                    compound, created = Compound.objects.get_or_create(
                        chembl_id=mol_data.get('molecule_chembl_id'),
                        defaults={
                            'name': mol_data.get('pref_name', mol_data.get('molecule_chembl_id', 'Unknown'))[:255],
                            'description': self._create_compound_description(mol_data),
                            'smiles': smiles[:500],
                            'molecular_weight': props.get('mw_freebase'),
                            'molecular_formula': props.get('molecular_formula', ''),
                            'logp': props.get('alogp'),
                            'tpsa': props.get('psa'),
                            'hbd': props.get('hbd'),
                            'hba': props.get('hba'),
                            'rotatable_bonds': props.get('rtb'),
                            'aliases': ', '.join(mol_data.get('molecule_synonyms', [])[:5])[:500],
                        }
                    )
                    
                    if created:
                        # Add random categories
                        if categories:
                            compound.categories.add(*random.sample(categories, min(3, len(categories))))
                        total_created += 1
                        
                except Exception as e:
                    logger.error(f"Error creating compound: {e}")
                    continue
            
            logger.info(f"Processed page {page + 1}, created {total_created} compounds so far")
            
            if limit and total_created >= limit:
                break
        
        logger.info(f"Created {total_created} compounds from ChEMBL")
    
    def _create_compound_description(self, mol_data: Dict) -> str:
        """Create a compound description from ChEMBL data"""
        parts = []
        
        if mol_data.get('molecule_type'):
            parts.append(f"Molecule type: {mol_data['molecule_type']}")
        
        if mol_data.get('max_phase'):
            phases = {
                0: "Preclinical",
                1: "Phase I",
                2: "Phase II", 
                3: "Phase III",
                4: "Approved"
            }
            parts.append(f"Development phase: {phases.get(mol_data['max_phase'], 'Unknown')}")
        
        props = mol_data.get('molecule_properties') or {}
        mw_value = props.get('mw_freebase')
        if mw_value is not None:
            try:
                mw_float = float(mw_value)
            except (TypeError, ValueError):
                mw_float = None
            if mw_float is not None:
                parts.append(f"Molecular weight: {mw_float:.2f} Da")
        
        if props.get('molecular_formula'):
            parts.append(f"Formula: {props['molecular_formula']}")
        
        return '. '.join(parts)
    
    def populate_mechanisms_from_chembl(self, limit: int = None):
        """Populate mechanisms of action from ChEMBL"""
        logger.info("Populating mechanisms from ChEMBL...")
        print("🔧 Starting mechanism population from ChEMBL database...")
        
        max_requests = 5 if not self.no_limits else 50
        mechanisms_per_request = 1000
        total_created = 0
        
        print(f"📊 Configuration: max_requests={max_requests}, per_request={mechanisms_per_request}")
        
        for page in range(max_requests):
            print(f"🌐 Fetching page {page + 1}/{max_requests} from ChEMBL mechanisms API...")
            offset = page * mechanisms_per_request
            data = self.chembl.get_mechanisms(limit=mechanisms_per_request, offset=offset)
            
            if not data or 'mechanisms' not in data:
                print(f"⚠️  No data received for page {page + 1}, stopping...")
                break
            
            mechanisms = data['mechanisms']
            if not mechanisms:
                print(f"⚠️  Empty mechanisms list for page {page + 1}, stopping...")
                break
            
            print(f"📋 Processing {len(mechanisms)} mechanisms from page {page + 1}...")
            
            processed_count = 0
            for mech_data in mechanisms:
                try:
                    # Get compound
                    compound = None
                    if mech_data.get('molecule_chembl_id'):
                        compound = Compound.objects.filter(chembl_id=mech_data['molecule_chembl_id']).first()
                    
                    if not compound:
                        continue
                    
                    # Get target
                    target = None
                    if mech_data.get('target_chembl_id'):
                        target = Target.objects.filter(chembl_id=mech_data['target_chembl_id']).first()
                    
                    # Create mechanism
                    mechanism, created = CompoundMechanismOfAction.objects.get_or_create(
                        target_name=mech_data.get('target_name', 'Unknown')[:255],
                        target_type=mech_data.get('target_type', 'Unknown')[:100],
                        target_interaction=mech_data.get('mechanism_of_action', 'Unknown')[:255],
                        defaults={
                            'compound': compound,
                            'direct_interaction': mech_data.get('direct_interaction', True),
                            'disease_efficacy': mech_data.get('disease_efficacy', True),
                            'selectivity_comment': mech_data.get('selectivity_comment', '')[:500],
                            'binding_site_comment': mech_data.get('binding_site_comment', '')[:500],
                        }
                    )
                    
                    if created:
                        total_created += 1
                        
                        # Create compound-target interaction if target exists
                        if target:
                            interaction, int_created = CompoundTargetInteraction.objects.get_or_create(
                                compound=compound,
                                target=target,
                                defaults={
                                    'mechanism': mech_data.get('mechanism_of_action', 'Unknown')[:100],
                                    'affinity_level': 'medium',
                                    'source': 'ChEMBL',
                                    'notes': f"Mechanism: {mech_data.get('mechanism_of_action', '')}"[:500]
                                }
                            )
                        
                    processed_count += 1
                    if processed_count % 100 == 0:
                        print(f"  ⚡ Processed {processed_count}/{len(mechanisms)} mechanisms, created {total_created} new ones...")
                        
                except Exception as e:
                    logger.error(f"Error creating mechanism: {e}")
                    continue
            
            print(f"✅ Page {page + 1} completed: processed {processed_count} mechanisms, total created: {total_created}")
            
            if limit and total_created >= limit:
                print(f"🎯 Reached limit of {limit} mechanisms, stopping...")
                break
        
        print(f"🎉 Mechanism population completed! Created {total_created} mechanisms from ChEMBL")
        logger.info(f"Created {total_created} mechanisms from ChEMBL")
    
    def populate_pathway_interactions_from_reactome(self, limit: int = None):
        """Reactome stage is disabled because pathway models are not present."""
        logger.info("Reactome pathway interaction staging skipped (models have been removed)")
        print("⚠️  Reactome pathway population skipped because TargetPathwayInteraction was removed from the schema.")
    
    def populate_compound_pathway_effects(self, limit: int = None):
        """Pathway effects stage is deferred because pathway models were removed."""
        logger.info("Compound pathway effect population skipped (models have been removed)")
        print("⚠️  Compound pathway effects cannot be computed because CompoundPathwayEffect was removed from the schema.")
    
    def populate_research_data(self):
        """Populate research-related data"""
        logger.info("Populating research data...")
        print("🔬 Starting research data population...")
        
        # Create research settings
        print("⚙️ Creating research settings...")
        settings, created = ResearchSettings.objects.get_or_create(
            id=1,
            defaults={
                'public_submissions_enabled': True,
                'require_review_flair': True,
                'higher_confirmation_rate': False,
                'ai_summaries_enabled': True,
                'min_votes_for_flair': 3,
                'verification_threshold': 0.7,
                'flagging_threshold': 0.3,
                'high_confidence_threshold': 0.8
            }
        )
        if created:
            print("  ✅ Created research settings")
        else:
            print("  ℹ️ Research settings already exist")
        
        # Create tags
        print("🏷️ Creating research snippet tags...")
        tags_data = [
            ('pharmacology', 'Pharmacological studies', '#007bff'),
            ('neuroscience', 'Neuroscience research', '#28a745'),
            ('clinical-trial', 'Clinical trial data', '#dc3545'),
            ('mechanism', 'Mechanism of action', '#ffc107'),
            ('safety', 'Safety and toxicology', '#fd7e14'),
            ('dosage', 'Dosage and administration', '#6f42c1'),
            ('interactions', 'Drug interactions', '#e83e8c'),
            ('metabolism', 'Drug metabolism', '#20c997'),
            ('subjective', 'Subjective effects', '#6c757d'),
            ('cognitive', 'Cognitive effects', '#17a2b8'),
        ]
        
        created_tags = []
        tags_created_count = 0
        for name, description, color in tags_data:
            tag, created = SnippetTag.objects.get_or_create(
                name=name,
                defaults={
                    'description': description,
                    'color': color
                }
            )
            created_tags.append(tag)
            if created:
                tags_created_count += 1
                print(f"  ✅ Created tag: {name}")
        
        print(f"🏷️ Created {tags_created_count} new tags")
        
        # Create user roles
        print("👥 Creating user roles...")
        user_roles_data = [
            ('researcher', 2.0, True),
            ('expert', 1.5, True),
            ('verified', 1.2, False),
            ('contributor', 1.0, False),
        ]
        
        users = list(User.objects.all()[:10])
        roles_created_count = 0
        for role_name, vote_weight, can_moderate in user_roles_data:
            if users:
                user = random.choice(users)
                role, created = UserRole.objects.get_or_create(
                    user=user,
                    defaults={
                        'role': role_name,
                        'vote_weight': vote_weight,
                        'can_moderate': can_moderate
                    }
                )
                if created:
                    roles_created_count += 1
                    print(f"  ✅ Assigned role '{role_name}' to user {user.username}")
        
        print(f"👥 Created {roles_created_count} user roles")
        
        # Create research snippets
        print("📝 Creating research snippets...")
        compounds = list(Compound.objects.all()[:50])
        snippet_types = ['research_paper', 'clinical_data', 'mechanism_study']
        
        if not compounds:
            print("⚠️  No compounds found for research snippets")
            return
        
        print(f"📊 Found {len(compounds)} compounds for snippet creation")
        
        imported_pubmed = self.populate_pubmed_snippets(compounds, created_tags, limit_per_compound=2)
        if imported_pubmed:
            print(f"📰 Imported {imported_pubmed} PubMed-based snippets")

        if not self.allow_dummy_research:
            print("🚫 Dummy research snippet generation is disabled. Skipping synthetic snippets.")
            logger.info("Dummy research snippet generation skipped (allow_dummy_research=False)")
            return

        created_snippets = 0
        max_snippets = 100 if not self.no_limits else 1000
        
        print(f"🎯 Will create up to {max_snippets} research snippets")
        
        for i in range(max_snippets):
            if not compounds:
                break
                
            compound = random.choice(compounds)
            snippet_type = random.choice(snippet_types)
            
            abstract_override = None
            if snippet_type == 'research_paper':
                abstract_override = self._fetch_pubmed_abstract(compound)

            snippet = ResearchSnippet.objects.create(
                title=f"{snippet_type.replace('_', ' ').title()} for {compound.name}",
                content=self._generate_snippet_content(compound, snippet_type, abstract_override),
                compound=compound,
                snippet_type=snippet_type,
                status=random.choice(['draft', 'published', 'under_review']),
                visibility=random.choice(['public', 'registered_only', 'private']),
                created_by=self.admin_user,
                ai_generated=random.choice([True, False]),
                ai_summary=f"AI-generated summary for {compound.name} {snippet_type}",
                source_title=f"Research on {compound.name}",
                source_url=f"https://example.com/research/{compound.slug}" if hasattr(compound, 'slug') else None
            )
            
            # Add tags
            if created_tags:
                snippet.tags.add(*random.sample(created_tags, random.randint(1, 3)))
            
            # Add reviews
            
            created_snippets += 1
            if created_snippets % 25 == 0:
                print(f"  📝 Created {created_snippets} snippets...")
        
        print(f"🎉 Research data population completed! Created {created_snippets} research snippets")
        logger.info(f"Created {created_snippets} research snippets")
    
    def _generate_snippet_content(
        self,
        compound: Compound,
        snippet_type: str,
        abstract_override: Optional[str] = None
    ) -> str:
        """Generate detailed research snippet content (papers/clinical/mechanisms only)"""
        base_intro = (
            f"Title: Investigating {compound.name} in contemporary research.\n"
            f"Compound: {compound.name} (ChEMBL: {compound.chembl_id or 'unknown'})\n\n"
        )

        if snippet_type == 'research_paper':
            abstract_text = abstract_override or (
                "Abstract:\n"
                "  This work consolidates recent in vitro and in vivo findings, "
                "focusing on receptor binding profiles and downstream signaling.\n"
                "Methods:\n"
                "  - High-throughput binding assays across GPCR and kinase panels\n"
                "  - Dose-response behavioral experiments in rodent models\n"
                "  - RNA-seq for transcriptional footprinting\n"
                "Results:\n"
                f"  {compound.name} shows sub-100 nM potency on multiple neurotransmitter receptors "
                "with consistent activation across species. Transcriptomics highlight cAMP, calcium, "
                "and oxidative stress pathways.\n"
                "Conclusion:\n"
                "  Evidence supports further translational research; safety margins remain to be clarified.\n"
            )

            return base_intro + abstract_text

        if snippet_type == 'clinical_data':
            return (
                base_intro
                + "Clinical Study Summary:\n"
                "  Randomized, double-blind Phase II trial (N=98) examining safety and target engagement.\n"
                "Endpoints:\n"
                "  - Primary: tolerability and steady-state plasma levels\n"
                "  - Secondary: symptom reduction indices and biomarker shifts\n"
                "Findings:\n"
                "  - Well tolerated up to 60mg/day, no serious adverse events\n"
                "  - PK/PD modeling suggests linear exposure with consistent metabolite ratios\n"
                f"Implications:\n"
                f"  {compound.name} is a candidate for larger efficacy studies with enriched biomarker sampling.\n"
            )

        # mechanism_study fallback
        return (
            base_intro
            + "Mechanistic Insight:\n"
            "  Functional assays dissect how the compound alters target structure and signaling cascades.\n"
            "Observations:\n"
            "  - High selectivity ratio for the primary receptor, confirmed via mutagenesis\n"
            "  - Partial agonism modulates downstream phosphorylation of ERK1/2 and Akt\n"
            "  - Integrative pathway analysis connects the target to synaptic plasticity and neuroinflammation modules\n"
            "Recommendations:\n"
            "  Leverage these mechanistic insights to guide next-stage translational validation.\n"
        )

    def _fetch_pubmed_abstract(self, compound: Compound) -> Optional[str]:
        """Fetch a PubMed abstract for a compound to reuse as research content"""
        papers = self._search_pubmed_papers(compound.name, limit=1)
        if not papers:
            return None

        abstract = papers[0].get('summary') or papers[0].get('title')
        if abstract:
            return f"Abstract sourced from PubMed:\n  {abstract.strip()}\n"

        return None

    def _search_pubmed_papers(self, compound_name: str, limit: int = 2) -> List[Dict]:
        """Search PubMed for papers that mention a specific compound"""
        query = f"{compound_name} AND (pharmacology OR mechanism OR neurotransmitter)"
        search_results = self.pubmed.search(query, retmax=limit if not self.no_limits else limit * 2)

        id_list = search_results.get('esearchresult', {}).get('idlist', [])
        return self.pubmed.fetch_summaries(id_list)

    def populate_pubmed_snippets(
        self,
        compounds: List[Compound],
        tags: List[SnippetTag],
        limit_per_compound: int = 2
    ) -> int:
        """Import vetted PubMed results as research snippets"""
        if not compounds:
            return 0

        max_compounds = 20 if self.no_limits else 10
        imported = 0

        for compound in compounds[:max_compounds]:
            papers = self._search_pubmed_papers(compound.name, limit=limit_per_compound)
            if not papers:
                continue

            for paper in papers:
                uid = paper.get('uid')
                if not uid:
                    continue

                source_url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
                summary = paper.get('summary') or paper.get('title') or f"PubMed summary for {compound.name}"

                snippet, created = ResearchSnippet.objects.get_or_create(
                    compound=compound,
                    source_url=source_url,
                    defaults={
                        'title': paper.get('title') or f"PubMed research for {compound.name}",
                        'content': summary,
                        'snippet_type': 'pharmacology',
                        'visibility': 'public',
                        'status': 'verified',
                        'created_by': self.admin_user,
                        'ai_generated': False,
                        'ai_summary': f"Imported from PubMed ({paper.get('pubdate', 'unknown date')})",
                        'source_title': paper.get('title'),
                        'doi': paper.get('doi', ''),
                    }
                )

                if created:
                    imported += 1

                    if tags:
                        snippet.tags.add(*random.sample(tags, min(2, len(tags))))

        logger.info(f"Imported {imported} PubMed research snippets")
        return imported
    
    def populate_user_data(self):
        """Populate user-related data"""
        logger.info("Populating user data...")
        print("👥 Starting user data population...")
        
        # Create additional users
        user_data = [
            ('researcher1', 'researcher1@neurobin.com', 'Research', 'User'),
            ('expert1', 'expert1@neurobin.com', 'Expert', 'Reviewer'),
            ('contributor1', 'contrib1@neurobin.com', 'Contributor', 'One'),
            ('moderator1', 'mod1@neurobin.com', 'Moderator', 'User'),
        ]
        
        print(f"🔧 Creating {len(user_data)} additional users...")
        created_users = []
        for username, email, first_name, last_name in user_data:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'is_active': True
                }
            )
            if created:
                user.set_password('password123')
                user.save()
                created_users.append(user)
                print(f"  ✅ Created user: {username}")
        
        print(f"👤 Created {len(created_users)} new users")
        
        # Create user profiles
        print("📝 Creating user profiles for users without profiles...")
        users_without_profiles = User.objects.filter(profile__isnull=True)
        profile_count = 0
        
        for user in users_without_profiles:
            UserProfile.objects.create(
                user=user,
                bio=f"Bio for {user.get_full_name() or user.username}",
                location=random.choice(['New York', 'London', 'Tokyo', 'Berlin', 'San Francisco']),
                website=f"https://{user.username}.example.com"
            )
            profile_count += 1
            print(f"  ✅ Created profile for: {user.username}")
        
        print(f"🎉 User data population completed! Created {profile_count} user profiles")
        logger.info(f"Created user profiles for all users")
    
    
    
    def populate_effect_windows(self):
        """Build effect windows based on ChEMBL-derived properties"""
        logger.info("Populating effect windows from ChEMBL metadata...")

        compounds = Compound.objects.filter(chembl_id__isnull=False)[:50]
        if not compounds:
            logger.warning("No compounds with ChEMBL IDs found for effect windows")
            return

        created_windows = 0

        for compound in compounds:
            chembl_data = self.chembl.get_molecule_details(compound.chembl_id)
            if not chembl_data or not chembl_data.get('molecules'):
                continue

            molecule = chembl_data['molecules'][0]
            props = molecule.get('molecule_properties') or {}

            logp = self._safe_float(props.get('alogp') or props.get('logp'))
            psa = self._safe_float(props.get('psa'))
            hbd = self._safe_float(props.get('hbd'))
            hba = self._safe_float(props.get('hba'))
            rtb = self._safe_float(props.get('rtb'))
            mw = self._safe_float(props.get('mw_freebase'), default=200)

            onset = max(5, min(90, int(120 - (logp or 0) * 5)))
            peak_min = onset + max(20, int(psa / 3) + 10)
            peak_max = peak_min + max(25, int(hbd * 8) + 10)
            duration = peak_max + max(90, int((hba + rtb) * 10) + 30)
            half_life = max(30, int(mw / 2))

            effect_shape = 'flat-top' if logp and logp > 3 else 'bell'

            window, created = EffectWindow.objects.update_or_create(
                compound=compound,
                effect_shape=effect_shape,
                defaults={
                    'onset_minutes': onset,
                    'peak_min_minutes': peak_min,
                    'peak_max_minutes': peak_max,
                    'duration_minutes': duration,
                    'half_life_minutes': half_life,
                    'notes': f"Effect profile derived from ChEMBL properties: logP={logp}, PSA={psa}",
                    'created_by': self.admin_user
                }
            )

            if created:
                created_windows += 1

        logger.info(f"Created/updated {created_windows} effect windows from ChEMBL")
    
    def _categorize_mechanism(self, mechanism: Optional[str]) -> str:
        """Convert mechanism string to a broad category"""
        mech = (mechanism or '').lower()
        if not mech:
            return 'unknown'

        if mech in self.ACTIVATING_MECHANISMS:
            return 'activating'
        if mech in self.INHIBITING_MECHANISMS:
            return 'inhibiting'
        if mech in self.MODULATING_MECHANISMS:
            return 'modulating'

        return 'unknown'

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """Convert values to float safely"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _determine_interaction_type(self, mechanism_a: Optional[str], mechanism_b: Optional[str]) -> str:
        """Derive compound-compound interaction type from the two mechanisms"""
        mech_a = (mechanism_a or '').lower()
        mech_b = (mechanism_b or '').lower()
        cat_a = self._categorize_mechanism(mech_a)
        cat_b = self._categorize_mechanism(mech_b)

        receptor_mechanisms = {'agonist', 'antagonist', 'partial_agonist', 'inverse_agonist'}

        if mech_a in receptor_mechanisms and mech_b in receptor_mechanisms:
            if cat_a == 'activating' and cat_b == 'activating':
                return 'synergistic'
            if cat_a == 'inhibiting' and cat_b == 'inhibiting':
                return 'competitive'
            return 'receptor_competition'

        if 'substrate' in {mech_a, mech_b}:
            return 'competitive_metabolism'

        if 'inducer' in {mech_a, mech_b} or 'upregulator' in {mech_a, mech_b}:
            return 'enzyme_induction'

        inhibitor_terms = {'inhibitor', 'blocker', 'antagonist', 'nam'}
        if inhibitor_terms.intersection({mech_a, mech_b}):
            if cat_a == 'inhibiting' and cat_b == 'inhibiting':
                return 'enzyme_inhibition'
            return 'antagonistic'

        if 'modulating' in {cat_a, cat_b}:
            if 'activating' in {cat_a, cat_b}:
                return 'potentiation'
            return 'additive'

        if cat_a == 'activating' and cat_b == 'activating':
            return 'synergistic'

        if 'activating' in {cat_a, cat_b} and 'inhibiting' in {cat_a, cat_b}:
            return 'antagonistic'

        if cat_a == 'inhibiting' and cat_b == 'inhibiting':
            return 'antagonistic'

        return 'unknown'

    def populate_compound_interactions(self):
        """Populate compound-to-compound target interactions using real mechanisms"""
        logger.info("Populating compound interactions from target mechanisms...")

        max_targets = 20 if not self.no_limits else 100
        targets = list(
            Target.objects.annotate(num_interactions=Count('compound_interactions'))
            .filter(num_interactions__gt=1)
            .order_by('-num_interactions')[:max_targets]
        )
        users = list(User.objects.all())

        if not targets or not users:
            logger.warning("Insufficient data for compound interactions")
            return

        created_interactions = 0
        max_interactions = 100 if not self.no_limits else 1000
        pair_limit = 3 if not self.no_limits else 12

        for target in targets:
            if created_interactions >= max_interactions:
                break

            interactions = list(target.compound_interactions.select_related('compound'))
            if len(interactions) < 2:
                continue

            pairs = list(combinations(interactions, 2))
            random.shuffle(pairs)

            for interaction_a, interaction_b in pairs[:pair_limit]:
                if created_interactions >= max_interactions:
                    break

                if interaction_a.compound == interaction_b.compound:
                    continue

                interaction_type = self._determine_interaction_type(
                    interaction_a.mechanism,
                    interaction_b.mechanism
                )

                compound_pair = sorted(
                    [interaction_a.compound, interaction_b.compound],
                    key=lambda c: c.pk
                )

                description = (
                    f"{interaction_a.compound.name} ({interaction_a.mechanism}) vs "
                    f"{interaction_b.compound.name} ({interaction_b.mechanism}) @ {target.name}"
                )

                interaction, created = CompoundToCompoundTargetInteraction.objects.get_or_create(
                    compound_a=compound_pair[0],
                    compound_b=compound_pair[1],
                    target=target,
                    defaults={
                        'interaction_type': interaction_type,
                        'description': description,
                        'confidence': random.choice(['high', 'medium', 'low']),
                        'source': 'ChEMBL-derived',
                        'created_by': random.choice(users)
                    }
                )

                if created:
                    created_interactions += 1

        logger.info(f"Created {created_interactions} compound interactions")
    
    
    def run_full_population(self):
        """Run complete data population"""
        logger.info("Starting full data population...")
        
        try:
            # Basic data types
            self.populate_action_types()
            self.populate_target_types()
            self.populate_compound_categories()
            
            # Core entities from external APIs
            self.populate_targets_from_chembl(limit=None if self.no_limits else 500)
            self.populate_compounds_from_chembl(limit=None if self.no_limits else 500)
            
            # Relationships and interactions
            self.populate_mechanisms_from_chembl(limit=None if self.no_limits else 1000)
            self.populate_pathway_interactions_from_reactome(limit=None if self.no_limits else 1000)
            self.populate_compound_pathway_effects(limit=None if self.no_limits else 1000)
            
            # User and community data
            self.populate_user_data()
            self.populate_research_data()
            
            # Derived content
            self.populate_effect_windows()
            self.populate_compound_interactions()
            
            logger.info("Data population completed successfully!")
            
        except Exception as e:
            logger.error(f"Error during data population: {e}")
            raise

def main():
    """Main execution function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Populate Neurobin database with comprehensive data')
    parser.add_argument('--full', action='store_true', help='Run full data population')
    parser.add_argument('--no-limits', action='store_true', help='Remove all limits on data fetching')
    parser.add_argument('--targets-only', action='store_true', help='Only populate targets')
    parser.add_argument('--compounds-only', action='store_true', help='Only populate compounds')
    parser.add_argument('--research-only', action='store_true', help='Only populate research data')
    parser.add_argument(
        '--allow-dummy-research',
        action='store_true',
        help='Allow synthetic research snippets (placeholder content) to be created'
    )
    
    args = parser.parse_args()
    
    populator = DataPopulator(
        no_limits=args.no_limits,
        allow_dummy_research=args.allow_dummy_research,
    )
    
    if args.full:
        populator.run_full_population()
    elif args.targets_only:
        populator.populate_action_types()
        populator.populate_target_types()
        populator.populate_targets_from_chembl()
    elif args.compounds_only:
        populator.populate_compound_categories()
        populator.populate_compounds_from_chembl()
    elif args.research_only:
        populator.populate_research_data()
    else:
        print("Please specify --full or a specific data type to populate")
        print("Use --help for more options")

if __name__ == '__main__':
    main()
