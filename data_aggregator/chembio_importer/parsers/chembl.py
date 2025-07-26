"""
ChEMBL API client for retrieving compound and target data
"""
import logging
from typing import List, Dict, Any, Optional, Iterator, Tuple
from tqdm import tqdm

from chembl_webresource_client.new_client import new_client

from ..config import CHEMBL_BATCH_SIZE, CHEMBL_TIMEOUT, CHEMBL_MAX_COMPOUNDS_PER_REQUEST
from ..throttler import rate_limited, retry_on_failure, api_throttler
from ..utils import (
    validate_smiles, validate_inchi, calculate_molecular_properties,
    normalize_activity_value, clean_compound_name, extract_gene_symbol,
    parse_chembl_activity_relation, log_data_quality_issues
)

logger = logging.getLogger(__name__)


class ChEMBLClient:
    """ChEMBL API client with rate limiting and comprehensive data extraction"""
    
    def __init__(self):
        self.molecules = new_client.molecule
        self.targets = new_client.target
        self.activities = new_client.activity
        self.mechanisms = new_client.mechanism
        self.drug_indications = new_client.drug_indication
        
        # Set timeout
        try:
            self.molecules.set_format('json')
            self.targets.set_format('json')
            self.activities.set_format('json')
            self.mechanisms.set_format('json')
        except Exception as e:
            logger.warning(f"Could not set ChEMBL client format: {e}")
    
    @rate_limited()
    @retry_on_failure()
    def get_compound_count(self) -> int:
        """Get total number of compounds in ChEMBL"""
        try:
            # Use a simple filter to get total count
            result = self.molecules.filter(max_phase__gte=0).count()
            return result
        except Exception as e:
            logger.error(f"Error getting compound count: {e}")
            return 0
    
    @rate_limited()
    @retry_on_failure()
    def get_compounds_batch(self, offset: int = 0, limit: int = CHEMBL_BATCH_SIZE) -> List[Dict[str, Any]]:
        """Get a batch of compounds with comprehensive data"""
        api_throttler.wait_for_endpoint('chembl_molecules', 2.0)
        
        try:
            # Get compounds with basic filtering - prefer approved drugs with names
            compounds = self.molecules.filter(
                molecule_type='Small molecule',
                max_phase=4  # Approved drugs
            ).only([
                'molecule_chembl_id', 'pref_name', 'molecule_synonyms',
                'molecule_structures', 'molecule_properties',
                'max_phase', 'first_approval', 'therapeutic_flag',
                'molecule_type', 'natural_product', 'oral', 'topical',
                'black_box_warning', 'availability_type'
            ])[offset:offset + limit]
            
            processed_compounds = []
            for compound in compounds:
                try:
                    processed = self._process_compound_data(compound)
                    if processed:
                        processed_compounds.append(processed)
                except Exception as e:
                    logger.error(f"Error processing compound {compound.get('molecule_chembl_id')}: {e}")
            
            return processed_compounds
            
        except Exception as e:
            logger.error(f"Error getting compounds batch (offset={offset}, limit={limit}): {e}")
            return []
    
    def _process_compound_data(self, compound_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process raw ChEMBL compound data into standardized format"""
        chembl_id = compound_data.get('molecule_chembl_id')
        if not chembl_id:
            return None
        
        # Basic compound information
        name = clean_compound_name(compound_data.get('pref_name', ''))
        
        # Structure data
        structures = compound_data.get('molecule_structures') or {}
        canonical_smiles = structures.get('canonical_smiles')
        inchi = structures.get('standard_inchi')
        inchi_key = structures.get('standard_inchi_key')
        
        # Validate structures
        if canonical_smiles and not validate_smiles(canonical_smiles):
            logger.warning(f"Invalid SMILES for {chembl_id}: {canonical_smiles}")
            canonical_smiles = None
        
        if inchi and not validate_inchi(inchi):
            logger.warning(f"Invalid InChI for {chembl_id}: {inchi}")
            inchi = None
        
        # Molecular properties
        properties = compound_data.get('molecule_properties') or {}
        molecular_properties = {
            'molecular_weight': properties.get('full_mwt'),
            'logp': properties.get('alogp'),
            'alogp': properties.get('alogp'),
            'tpsa': properties.get('psa'),
            'hbd': properties.get('hbd'),
            'hba': properties.get('hba'),
            'rotatable_bonds': properties.get('rtb'),
        }
        
        # Calculate additional properties if SMILES available
        if canonical_smiles:
            calculated_props = calculate_molecular_properties(canonical_smiles)
            molecular_properties.update(calculated_props)
        
        # Clinical information
        max_phase = compound_data.get('max_phase')
        first_approval = compound_data.get('first_approval')
        therapeutic_flag = compound_data.get('therapeutic_flag')
        
        # Determine approval status
        approval_status = 'unknown'
        if max_phase == 4:
            approval_status = 'approved'
        elif max_phase == 3:
            approval_status = 'phase_3'
        elif max_phase == 2:
            approval_status = 'phase_2'
        elif max_phase == 1:
            approval_status = 'phase_1'
        elif max_phase == 0:
            approval_status = 'preclinical'
        
        # Compound type classification
        compound_type = compound_data.get('molecule_type', 'unknown')
        if compound_data.get('natural_product'):
            compound_type = 'natural_product'
        
        # Routes of administration
        routes = []
        if compound_data.get('oral'):
            routes.append('oral')
        if compound_data.get('topical'):
            routes.append('topical')
        
        # Synonyms
        synonyms_data = compound_data.get('molecule_synonyms') or []
        synonyms = []
        for syn in synonyms_data:
            if isinstance(syn, dict):
                synonym_name = syn.get('molecule_synonym')
                synonym_type = syn.get('syn_type')
                if synonym_name:
                    synonyms.append({
                        'name': synonym_name,
                        'type': synonym_type,
                        'source': 'ChEMBL'
                    })
        
        # Metadata
        metadata = {
            'therapeutic_flag': therapeutic_flag,
            'black_box_warning': compound_data.get('black_box_warning'),
            'availability_type': compound_data.get('availability_type'),
            'routes': routes,
            'source': 'ChEMBL',
            'import_date': None  # Will be set during import
        }
        
        result = {
            'chembl_id': chembl_id,
            'name': name,
            'canonical_smiles': canonical_smiles,
            'inchi': inchi,
            'inchi_key': inchi_key,
            'compound_type': compound_type,
            'approval_status': approval_status,
            'max_phase': max_phase,
            'first_approval': first_approval,
            'synonyms': synonyms,
            'additional_metadata': metadata,
            **molecular_properties
        }
        
        # Log data quality issues
        log_data_quality_issues(result, 'compound', chembl_id)
        
        return result
    
    @rate_limited()
    @retry_on_failure()
    def get_compound_by_id(self, chembl_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific compound"""
        api_throttler.wait_for_endpoint('chembl_molecule_detail', 1.0)
        
        try:
            compound = self.molecules.get(chembl_id)
            if compound:
                return self._process_compound_data(compound)
        except Exception as e:
            logger.error(f"Error getting compound {chembl_id}: {e}")
        
        return None
    
    @rate_limited()
    @retry_on_failure()
    def get_compound_targets(self, chembl_id: str) -> List[Dict[str, Any]]:
        """Get targets for a specific compound"""
        api_throttler.wait_for_endpoint('chembl_activities', 1.5)
        
        try:
            # Get bioactivities for the compound
            activities = self.activities.filter(
                molecule_chembl_id=chembl_id,
                type__in=['IC50', 'EC50', 'Ki', 'Kd', 'ED50', 'LD50', 'MIC']
            ).only([
                'target_chembl_id', 'type', 'value', 'units', 'relation',
                'confidence_score', 'data_validity_comment',
                'assay_chembl_id', 'document_chembl_id'
            ])
            
            target_data = {}
            interactions = []
            
            for activity in activities:
                target_chembl_id = activity.get('target_chembl_id')
                if not target_chembl_id:
                    continue
                
                # Get target details if not already cached
                if target_chembl_id not in target_data:
                    target_info = self.get_target_by_id(target_chembl_id)
                    if target_info:
                        target_data[target_chembl_id] = target_info
                
                # Process activity data
                activity_value = normalize_activity_value(
                    activity.get('value'), 
                    activity.get('units')
                )
                
                # Get target name for the interaction
                target_name = ''
                if target_chembl_id in target_data:
                    target_info = target_data[target_chembl_id]
                    target_name = target_info.get('name') or target_info.get('gene_symbol') or ''
                
                interaction = {
                    'target_chembl_id': target_chembl_id,
                    'target_name': target_name,  # Add target name for effect profiles
                    'activity_type': activity.get('type'),
                    'activity_value': activity_value,
                    'activity_units': 'nM',  # Normalized to nM
                    'activity_relation': parse_chembl_activity_relation(activity.get('relation')),
                    'confidence_score': activity.get('confidence_score'),
                    'data_validity_comment': activity.get('data_validity_comment'),
                    'assay_chembl_id': activity.get('assay_chembl_id'),
                    'document_chembl_id': activity.get('document_chembl_id'),
                    'source': 'ChEMBL'
                }
                
                interactions.append(interaction)
            
            return interactions
            
        except Exception as e:
            logger.error(f"Error getting targets for compound {chembl_id}: {e}")
            return []
    
    @rate_limited()
    @retry_on_failure()
    def get_compound_mechanisms(self, chembl_id: str) -> List[Dict[str, Any]]:
        """Get mechanism of action data for a compound"""
        api_throttler.wait_for_endpoint('chembl_mechanisms', 1.5)
        
        try:
            mechanisms = self.mechanisms.filter(molecule_chembl_id=chembl_id)
            
            mechanism_data = []
            for mech in mechanisms:
                target_chembl_id = mech.get('target_chembl_id')
                mechanism_type = mech.get('mechanism_of_action')
                
                if target_chembl_id and mechanism_type:
                    # Get target name
                    target_name = ''
                    target_info = self.get_target_by_id(target_chembl_id)
                    if target_info:
                        target_name = target_info.get('name') or target_info.get('gene_symbol') or ''
                    
                    mechanism_data.append({
                        'target_chembl_id': target_chembl_id,
                        'target_name': target_name,  # Add target name for effect profiles
                        'mechanism': mechanism_type,
                        'action_type': mech.get('action_type'),
                        'direct_interaction': mech.get('direct_interaction'),
                        'molecular_mechanism': mech.get('molecular_mechanism'),
                        'disease_efficacy': mech.get('disease_efficacy'),
                        'source': 'ChEMBL'
                    })
            
            return mechanism_data
            
        except Exception as e:
            logger.error(f"Error getting mechanisms for compound {chembl_id}: {e}")
            return []
    
    @rate_limited()
    @retry_on_failure()
    def get_target_by_id(self, target_chembl_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific target"""
        api_throttler.wait_for_endpoint('chembl_target_detail', 1.0)
        
        try:
            target = self.targets.get(target_chembl_id)
            if not target:
                return None
            
            # Extract gene symbol
            gene_symbol = extract_gene_symbol(target.get('pref_name', ''))
            
            result = {
                'chembl_id': target_chembl_id,
                'name': target.get('pref_name'),
                'gene_symbol': gene_symbol,
                'organism': target.get('organism'),
                'target_type': target.get('target_type'),
                'protein_class': target.get('protein_class_desc'),
                'description': target.get('target_description'),
                'additional_metadata': {
                    'source': 'ChEMBL',
                    'tax_id': target.get('tax_id'),
                    'species_group_flag': target.get('species_group_flag')
                }
            }
            
            # Extract cross-references
            cross_refs = target.get('target_cross_references') or []
            for ref in cross_refs:
                if isinstance(ref, dict):
                    source = ref.get('xref_src_db')
                    ref_id = ref.get('xref_id')
                    if source == 'UniProt' and ref_id:
                        result['uniprot_id'] = ref_id
                    elif source == 'Ensembl' and ref_id:
                        result['ensembl_id'] = ref_id
            
            log_data_quality_issues(result, 'target', target_chembl_id)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting target {target_chembl_id}: {e}")
            return None
    
    def get_all_compounds(self, limit: Optional[int] = None, 
                         progress_callback: Optional[callable] = None) -> Iterator[Dict[str, Any]]:
        """Generator to iterate through all compounds in ChEMBL"""
        try:
            total_count = self.get_compound_count() if not limit else limit
            logger.info(f"Starting to fetch {total_count} compounds from ChEMBL")
            
            processed_count = 0
            offset = 0
            
            with tqdm(total=total_count, desc="Fetching ChEMBL compounds") as pbar:
                while processed_count < total_count:
                    batch_limit = min(CHEMBL_BATCH_SIZE, total_count - processed_count)
                    
                    compounds = self.get_compounds_batch(offset=offset, limit=batch_limit)
                    
                    if not compounds:
                        logger.warning(f"No compounds returned for offset {offset}")
                        break
                    
                    for compound in compounds:
                        yield compound
                        processed_count += 1
                        pbar.update(1)
                        
                        if progress_callback:
                            progress_callback(processed_count, total_count)
                    
                    offset += batch_limit
                    
                    if len(compounds) < batch_limit:
                        # Fewer compounds returned than requested, likely at end
                        break
            
            logger.info(f"Finished fetching {processed_count} compounds from ChEMBL")
            
        except Exception as e:
            logger.error(f"Error in get_all_compounds: {e}")
            raise
    
    def get_compound_with_targets_and_mechanisms(self, chembl_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive compound data including targets and mechanisms"""
        compound = self.get_compound_by_id(chembl_id)
        if not compound:
            return None
        
        # Get targets and activities
        targets = self.get_compound_targets(chembl_id)
        compound['target_interactions'] = targets
        
        # Get mechanisms
        mechanisms = self.get_compound_mechanisms(chembl_id)
        compound['mechanisms'] = mechanisms
        
        return compound


# Global client instance
chembl_client = ChEMBLClient()
