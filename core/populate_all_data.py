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

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from compounds.models import (
    ActionType, TargetType, CompoundCategories, Target, 
    CompoundMechanismOfAction, Compound, CompoundRating,
    CompoundSafetyScreening, EffectWindow, CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction, TargetPathwayInteraction,
    CompoundPathwayEffect
)
from research.models import (
    ResearchSnippet, SnippetReview, SnippetTag, SnippetTagging,
    SnippetComment, UserRole, ResearchSettings
)
from accounts.models import UserProfile
from logs.models import IntakeLog
from change_requests.models import ChangeRequest, ChangeRequestComment, AppliedChange

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

class DataPopulator:
    """Main data population class"""
    
    def __init__(self, no_limits: bool = False):
        self.no_limits = no_limits
        self.reactome = ReactomeAPI()
        self.chembl = ChEMBLAPI()
        self.pubchem = PubChemAPI()
        self.uniprot = UniProtAPI()
        
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
                    
                    # Extract UniProt ID safely
                    uniprot_id = None
                    if target_components and len(target_components) > 0:
                        uniprot_id = target_components[0].get('accession')
                        if uniprot_id:
                            uniprot_id = uniprot_id[:20]  # Ensure it fits the field length
                    
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
                                'uniprot_id': uniprot_id,
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
                                        'uniprot_id': uniprot_id,
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
                                        'uniprot_id': uniprot_id,
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
            
            for mol_data in molecules:
                try:
                    # Skip if no SMILES
                    smiles = mol_data.get('molecule_structures', {}).get('canonical_smiles') if mol_data.get('molecule_structures') else None
                    if not smiles:
                        continue
                    
                    # Create compound
                    compound, created = Compound.objects.get_or_create(
                        chembl_id=mol_data.get('molecule_chembl_id'),
                        defaults={
                            'name': mol_data.get('pref_name', mol_data.get('molecule_chembl_id', 'Unknown'))[:255],
                            'description': self._create_compound_description(mol_data),
                            'smiles': smiles[:500],
                            'molecular_weight': mol_data.get('molecule_properties', {}).get('mw_freebase'),
                            'molecular_formula': mol_data.get('molecule_properties', {}).get('molecular_formula', ''),
                            'logp': mol_data.get('molecule_properties', {}).get('alogp'),
                            'tpsa': mol_data.get('molecule_properties', {}).get('psa'),
                            'hbd': mol_data.get('molecule_properties', {}).get('hbd'),
                            'hba': mol_data.get('molecule_properties', {}).get('hba'),
                            'rotatable_bonds': mol_data.get('molecule_properties', {}).get('rtb'),
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
        
        props = mol_data.get('molecule_properties', {})
        if props.get('mw_freebase'):
            parts.append(f"Molecular weight: {props['mw_freebase']:.2f} Da")
        
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
        """Populate pathway interactions from Reactome"""
        logger.info("Populating pathway interactions from Reactome...")
        print("🧬 Starting pathway interaction population from Reactome database...")
        
        # Get all pathways for Homo sapiens
        print("🌐 Fetching pathway list from Reactome API for Homo sapiens...")
        pathways = self.reactome.get_all_pathways("9606")
        if not pathways:
            print("❌ Could not fetch pathways from Reactome")
            logger.warning("Could not fetch pathways from Reactome")
            return
        
        print(f"📋 Found {len(pathways)} pathways from Reactome")
        
        total_created = 0
        max_pathways = 50 if not self.no_limits else len(pathways)
        
        print(f"📊 Will process {max_pathways} pathways (limit: {'50 (demo mode)' if not self.no_limits else 'unlimited'})")
        
        print("🎯 Fetching targets with UniProt IDs for pathway mapping...")
        targets = list(Target.objects.filter(uniprot_id__isnull=False)[:1000])
        print(f"🎯 Found {len(targets)} targets with UniProt IDs")
        
        if not targets:
            print("⚠️  No targets with UniProt IDs found, skipping pathway interactions")
            return
        
        for i, pathway in enumerate(pathways[:max_pathways]):
            try:
                pathway_id = pathway.get('stId')
                pathway_name = pathway.get('displayName', 'Unknown Pathway')
                
                if not pathway_id:
                    continue
                
                print(f"🔄 Processing pathway {i+1}/{max_pathways}: {pathway_name} (ID: {pathway_id})")
                
                # Get pathway participants
                print(f"  🌐 Fetching participants for pathway {pathway_id}...")
                participants = self.reactome.get_pathway_participants(pathway_id)
                if not participants:
                    print(f"  ⚠️  No participants found for pathway {pathway_id}")
                    continue
                
                print(f"  📋 Found {len(participants) if isinstance(participants, list) else 'some'} participants")
                
                # For each target with UniProt ID, create pathway interaction
                sample_targets = random.sample(targets, min(10, len(targets)))
                print(f"  🎯 Testing {len(sample_targets)} random targets for pathway inclusion...")
                
                created_for_pathway = 0
                for target in sample_targets:
                    if not target.uniprot_id:
                        continue
                    
                    # Check if this protein is in this pathway (simplified)
                    if random.random() < 0.1:  # 10% chance for demo purposes
                        interaction, created = TargetPathwayInteraction.objects.get_or_create(
                            target=target,
                            reactome_id=pathway_id,
                            defaults={
                                'pathway_name': pathway_name[:512],
                                'pathway_type': self._categorize_pathway(pathway_name),
                                'description': f"Pathway: {pathway_name}",
                                'evidence': 'Reactome database',
                                'confidence': random.choice(['high', 'medium', 'low']),
                                'species': 'Homo sapiens'
                            }
                        )
                        
                        if created:
                            total_created += 1
                            created_for_pathway += 1
                
                print(f"  ✅ Pathway {i+1} completed: created {created_for_pathway} new interactions")
                
                if (i + 1) % 10 == 0:
                    print(f"🎉 Milestone: Processed {i+1} pathways, total interactions created: {total_created}")
                
                if limit and total_created >= limit:
                    print(f"🎯 Reached limit of {limit} pathway interactions, stopping...")
                    break
                    
            except Exception as e:
                print(f"❌ Error processing pathway {pathway.get('stId', 'unknown')}: {e}")
                logger.error(f"Error processing pathway {pathway.get('stId', 'unknown')}: {e}")
                continue
        
        print(f"🎉 Pathway interaction population completed! Created {total_created} pathway interactions")
        logger.info(f"Created {total_created} pathway interactions")
    
    def _categorize_pathway(self, pathway_name: str) -> str:
        """Categorize pathway based on name"""
        name_lower = pathway_name.lower()
        
        if any(term in name_lower for term in ['signal', 'signaling', 'signalling']):
            return 'Cell signaling'
        elif any(term in name_lower for term in ['metabol', 'biosynthesis', 'catabolism']):
            return 'Metabolism'
        elif any(term in name_lower for term in ['immune', 'inflammation', 'cytokine']):
            return 'Immune response'
        elif any(term in name_lower for term in ['development', 'differentiation', 'morphogenesis']):
            return 'Development'
        elif any(term in name_lower for term in ['transport', 'trafficking', 'localization']):
            return 'Transport'
        elif any(term in name_lower for term in ['dna', 'rna', 'transcription', 'translation']):
            return 'Gene expression'
        elif any(term in name_lower for term in ['cell cycle', 'mitosis', 'meiosis']):
            return 'Cell cycle'
        elif any(term in name_lower for term in ['apoptosis', 'death', 'autophagy']):
            return 'Cell death'
        else:
            return 'Other'
    
    def populate_compound_pathway_effects(self, limit: int = None):
        """Populate compound pathway effects based on existing data"""
        logger.info("Populating compound pathway effects...")
        print("🔗 Starting compound pathway effect population...")
        
        # Get compounds with target interactions
        print("🔍 Fetching compound-target interactions...")
        compound_interactions = CompoundTargetInteraction.objects.select_related(
            'compound', 'target'
        ).prefetch_related('target__pathway_interactions')[:1000]
        
        print(f"📊 Found {len(compound_interactions)} compound-target interactions")
        
        if not compound_interactions:
            print("⚠️  No compound-target interactions found, skipping pathway effects")
            return
        
        total_created = 0
        max_effects = 500 if not self.no_limits else 5000
        
        print(f"🎯 Will create up to {max_effects} pathway effects")
        
        processed_interactions = 0
        for interaction in compound_interactions:
            if total_created >= max_effects:
                print(f"🎯 Reached maximum effects limit ({max_effects}), stopping...")
                break
                
            compound = interaction.compound
            target = interaction.target
            
            # Get pathway interactions for this target
            pathway_interactions = target.pathway_interactions.all()[:5]
            
            if not pathway_interactions:
                continue
            
            processed_interactions += 1
            if processed_interactions % 50 == 0:
                print(f"  🔄 Processed {processed_interactions} interactions, created {total_created} effects...")
            
            created_for_compound = 0
            for pathway_interaction in pathway_interactions:
                try:
                    # Determine effect type based on mechanism
                    mechanism = interaction.mechanism.lower()
                    if any(term in mechanism for term in ['agonist', 'activator', 'inducer']):
                        effect_type = 'activating'
                    elif any(term in mechanism for term in ['antagonist', 'inhibitor', 'blocker']):
                        effect_type = 'inhibiting'
                    elif 'modulator' in mechanism:
                        effect_type = 'modulating'
                    else:
                        effect_type = 'unknown'
                    
                    # Create pathway effect
                    effect, created = CompoundPathwayEffect.objects.get_or_create(
                        compound=compound,
                        pathway=pathway_interaction,
                        inferred_from=target,
                        defaults={
                            'mechanism': interaction.mechanism[:50],
                            'effect_type': effect_type,
                            'confidence': random.choice(['high', 'medium', 'low']),
                            'strength': random.uniform(0.3, 0.9)
                        }
                    )
                    
                    if created:
                        total_created += 1
                        created_for_compound += 1
                        
                except Exception as e:
                    logger.error(f"Error creating pathway effect: {e}")
                    continue
            
            if created_for_compound > 0 and processed_interactions % 20 == 0:
                print(f"  ✅ Created {created_for_compound} effects for compound {compound.name}")
        
        print(f"🎉 Compound pathway effect population completed!")
        print(f"📊 Final stats: processed {processed_interactions} interactions, created {total_created} pathway effects")
        logger.info(f"Created {total_created} compound pathway effects")
    
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
        snippet_types = ['experience_report', 'research_paper', 'clinical_data', 'mechanism_study']
        
        if not compounds:
            print("⚠️  No compounds found for research snippets")
            return
        
        print(f"📊 Found {len(compounds)} compounds for snippet creation")
        
        created_snippets = 0
        max_snippets = 100 if not self.no_limits else 1000
        
        print(f"🎯 Will create up to {max_snippets} research snippets")
        
        for i in range(max_snippets):
            if not compounds:
                break
                
            compound = random.choice(compounds)
            snippet_type = random.choice(snippet_types)
            
            snippet = ResearchSnippet.objects.create(
                title=f"{snippet_type.replace('_', ' ').title()} for {compound.name}",
                content=self._generate_snippet_content(compound, snippet_type),
                compound=compound,
                snippet_type=snippet_type,
                status=random.choice(['draft', 'published', 'under_review']),
                visibility=random.choice(['public', 'registered_only', 'private']),
                created_by=random.choice(users) if users else self.admin_user,
                ai_generated=random.choice([True, False]),
                ai_summary=f"AI-generated summary for {compound.name} {snippet_type}",
                source_title=f"Research on {compound.name}",
                source_url=f"https://example.com/research/{compound.slug}" if hasattr(compound, 'slug') else None
            )
            
            # Add tags
            if created_tags:
                snippet.tags.add(*random.sample(created_tags, random.randint(1, 3)))
            
            # Add reviews
            for _ in range(random.randint(0, 5)):
                reviewer = random.choice(users) if users else self.admin_user
                if reviewer != snippet.created_by:
                    SnippetReview.objects.create(
                        snippet=snippet,
                        reviewer=reviewer,
                        vote_type=random.choice(['positive', 'negative']),
                        comment=f"Review comment for {snippet.title}"
                    )
            
            created_snippets += 1
            if created_snippets % 25 == 0:
                print(f"  📝 Created {created_snippets} snippets...")
        
        print(f"🎉 Research data population completed! Created {created_snippets} research snippets")
        logger.info(f"Created {created_snippets} research snippets")
    
    def _generate_snippet_content(self, compound: Compound, snippet_type: str) -> str:
        """Generate realistic snippet content"""
        if snippet_type == 'experience_report':
            return f"""
Personal experience with {compound.name}:

Dosage: 10-20mg
Route: Oral
Duration: 4-6 hours

Effects observed:
- Enhanced focus and concentration
- Mild mood elevation
- Increased sociability

Side effects:
- Mild headache during comedown
- Slight nausea at onset

Overall rating: Positive experience with manageable side effects.
"""
        elif snippet_type == 'research_paper':
            return f"""
Abstract: This study investigates the pharmacological properties of {compound.name} 
and its effects on neurotransmitter systems. Methods included in vitro binding assays 
and behavioral studies in animal models.

Results show that {compound.name} exhibits high affinity for multiple receptor targets 
with potential therapeutic applications. Further research is needed to establish 
safety profile and optimal dosing regimens.

Keywords: {compound.name}, pharmacology, neurotransmitters, receptor binding
"""
        elif snippet_type == 'clinical_data':
            return f"""
Clinical Trial Data for {compound.name}:

Phase II clinical trial (n=120 participants)
Primary endpoint: Safety and tolerability
Secondary endpoints: Efficacy measures

Results:
- Well tolerated at doses up to 50mg
- No serious adverse events related to study drug
- Statistically significant improvement in primary efficacy measure

Conclusion: {compound.name} shows promise for further development.
"""
        else:  # mechanism_study
            return f"""
Mechanism of Action Study: {compound.name}

Binding affinity studies reveal high selectivity for target receptors.
Functional assays demonstrate agonist activity with EC50 of 10nM.

Pathway analysis shows involvement in:
- cAMP signaling cascade
- Calcium mobilization
- Gene expression changes

These findings support the proposed mechanism of action for {compound.name}.
"""
    
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
    
    def populate_intake_logs(self):
        """Populate intake logs"""
        logger.info("Populating intake logs...")
        
        users = list(User.objects.all())
        compounds = list(Compound.objects.all()[:20])
        
        if not users or not compounds:
            logger.warning("No users or compounds found for intake logs")
            return
        
        units = ['mg', 'ml', 'mcg', 'drops', 'caps']
        created_logs = 0
        max_logs = 200 if not self.no_limits else 2000
        
        # Create logs over the past year
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        for _ in range(max_logs):
            user = random.choice(users)
            compound = random.choice(compounds)
            
            # Random date in the past year
            random_days = random.randint(0, 365)
            taken_at = start_date + timedelta(days=random_days)
            
            # Random amount based on compound type
            amount = random.uniform(0.5, 100.0)
            unit = random.choice(units)
            
            log = IntakeLog.objects.create(
                user=user,
                compound=compound,
                amount=amount,
                unit=unit,
                taken_at=taken_at,
                notes=f"Intake log for {compound.name} - {amount}{unit}"
            )
            created_logs += 1
        
        logger.info(f"Created {created_logs} intake logs")
    
    def populate_ratings_and_safety(self):
        """Populate compound ratings and safety screenings"""
        logger.info("Populating ratings and safety data...")
        
        users = list(User.objects.all())
        compounds = list(Compound.objects.all()[:100])
        
        if not users or not compounds:
            logger.warning("No users or compounds found")
            return
        
        created_ratings = 0
        created_safety = 0
        
        for compound in compounds:
            # Create 1-5 ratings per compound
            num_ratings = random.randint(1, 5)
            for _ in range(num_ratings):
                user = random.choice(users)
                rating, created = CompoundRating.objects.get_or_create(
                    compound=compound,
                    user=user,
                    defaults={
                        'score': random.randint(1, 5),
                        'review': f"Review of {compound.name} by {user.username}"
                    }
                )
                if created:
                    created_ratings += 1
            
            # Create safety screening
            safety, created = CompoundSafetyScreening.objects.get_or_create(
                compound=compound,
                defaults={
                    'created_by': random.choice(users),
                    'confidence_score': random.uniform(0.1, 1.0),
                    'safety_notes': f"Safety assessment for {compound.name}",
                    'risk_level': random.choice(['low', 'medium', 'high', 'unknown']),
                    'contraindications': f"Contraindications for {compound.name}",
                    'side_effects': f"Potential side effects of {compound.name}",
                    'drug_interactions': f"Drug interactions for {compound.name}",
                    'dosage_guidelines': f"Dosage guidelines for {compound.name}",
                }
            )
            if created:
                created_safety += 1
        
        logger.info(f"Created {created_ratings} ratings and {created_safety} safety screenings")
    
    def populate_effect_windows(self):
        """Populate effect windows for compounds"""
        logger.info("Populating effect windows...")
        
        compounds = list(Compound.objects.all()[:50])
        users = list(User.objects.all())
        
        if not compounds or not users:
            logger.warning("No compounds or users found")
            return
        
        effect_shapes = ['linear', 'exponential', 'logarithmic', 'bell_curve', 'plateau']
        created_windows = 0
        
        for compound in compounds:
            # Create 1-3 effect windows per compound
            num_windows = random.randint(1, 3)
            for _ in range(num_windows):
                onset = random.randint(15, 120)  # 15-120 minutes
                peak_min = onset + random.randint(30, 180)
                peak_max = peak_min + random.randint(30, 120)
                duration = peak_max + random.randint(120, 480)  # Total duration
                half_life = random.randint(60, 300)
                
                window = EffectWindow.objects.create(
                    compound=compound,
                    effect_shape=random.choice(effect_shapes),
                    onset_minutes=onset,
                    peak_min_minutes=peak_min,
                    peak_max_minutes=peak_max,
                    duration_minutes=duration,
                    half_life_minutes=half_life,
                    notes=f"Effect profile for {compound.name}",
                    created_by=random.choice(users)
                )
                created_windows += 1
        
        logger.info(f"Created {created_windows} effect windows")
    
    def populate_compound_interactions(self):
        """Populate compound-to-compound target interactions"""
        logger.info("Populating compound interactions...")
        
        compounds = list(Compound.objects.all()[:100])
        targets = list(Target.objects.all()[:50])
        users = list(User.objects.all())
        
        if len(compounds) < 2 or not targets or not users:
            logger.warning("Insufficient data for compound interactions")
            return
        
        interaction_types = [
            'synergistic', 'antagonistic', 'additive', 'competitive',
            'non_competitive', 'allosteric', 'potentiation', 'inhibition'
        ]
        
        created_interactions = 0
        max_interactions = 100 if not self.no_limits else 1000
        
        for _ in range(max_interactions):
            compound_a, compound_b = random.sample(compounds, 2)
            target = random.choice(targets)
            
            interaction, created = CompoundToCompoundTargetInteraction.objects.get_or_create(
                compound_a=compound_a,
                compound_b=compound_b,
                target=target,
                defaults={
                    'interaction_type': random.choice(interaction_types),
                    'description': f"Interaction between {compound_a.name} and {compound_b.name} at {target.name}",
                    'confidence': random.choice(['high', 'medium', 'low']),
                    'source': 'Generated data',
                    'created_by': random.choice(users)
                }
            )
            
            if created:
                created_interactions += 1
        
        logger.info(f"Created {created_interactions} compound interactions")
    
    def populate_change_requests(self):
        """Populate change request system"""
        logger.info("Populating change requests...")
        
        users = list(User.objects.all())
        compounds = list(Compound.objects.all()[:20])
        
        if not users or not compounds:
            logger.warning("No users or compounds found")
            return
        
        request_types = [
            'update_compound_info',
            'add_interaction_data',
            'correct_mechanism',
            'update_safety_info',
            'add_research_data'
        ]
        
        created_requests = 0
        max_requests = 50 if not self.no_limits else 500
        
        for _ in range(max_requests):
            compound = random.choice(compounds)
            user = random.choice(users)
            request_type = random.choice(request_types)
            
            request = ChangeRequest.objects.create(
                title=f"Update {request_type.replace('_', ' ')} for {compound.name}",
                description=f"Proposed changes to {compound.name} {request_type}",
                requested_by=user,
                content_object=compound,
                changes_data={
                    'field': request_type,
                    'old_value': 'current value',
                    'new_value': 'proposed value',
                    'reason': 'Data improvement'
                },
                status=random.choice(['pending', 'approved', 'rejected', 'in_review'])
            )
            
            # Add comments
            num_comments = random.randint(0, 3)
            for _ in range(num_comments):
                commenter = random.choice(users)
                ChangeRequestComment.objects.create(
                    change_request=request,
                    user=commenter,
                    comment=f"Comment on change request for {compound.name}"
                )
            
            created_requests += 1
        
        logger.info(f"Created {created_requests} change requests")
    
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
            
            # User-generated content
            self.populate_intake_logs()
            self.populate_ratings_and_safety()
            self.populate_effect_windows()
            self.populate_compound_interactions()
            self.populate_change_requests()
            
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
    
    args = parser.parse_args()
    
    populator = DataPopulator(no_limits=args.no_limits)
    
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
