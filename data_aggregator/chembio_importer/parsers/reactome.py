"""
Reactome API client for retrieving pathway data
"""
import logging
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urljoin

from ..config import REACTOME_BASE_URL, REACTOME_TIMEOUT, REACTOME_SPECIES
from ..throttler import make_throttled_request, rate_limited, retry_on_failure
from ..utils import create_reactome_url, standardize_organism_name

logger = logging.getLogger(__name__)


class ReactomeClient:
    """Reactome API client for pathway data retrieval"""
    
    def __init__(self, base_url: str = REACTOME_BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.session_headers = {
            'Accept': 'application/json',
            'User-Agent': 'ChemBio-Importer/1.0'
        }
    
    @rate_limited()
    @retry_on_failure()
    def get_pathways_for_identifier(self, identifier: str, 
                                   identifier_type: str = 'uniprot') -> List[Dict[str, Any]]:
        """Get pathways for a given protein identifier (UniProt, Gene Symbol, etc.)"""
        try:
            # Construct URL based on identifier type
            if identifier_type.lower() == 'uniprot':
                url = f"{self.base_url}/data/pathways/low/entity/{identifier}"
            else:
                url = f"{self.base_url}/data/pathways/low/identifier/{identifier}"
            
            response = make_throttled_request(
                url, 
                endpoint_name='reactome_pathways',
                headers=self.session_headers,
                timeout=REACTOME_TIMEOUT
            )
            
            pathways_data = response.json()
            
            # Filter for human pathways if specified
            filtered_pathways = []
            for pathway in pathways_data:
                species = pathway.get('species', [])
                if isinstance(species, list) and species:
                    species_name = species[0].get('displayName', '')
                else:
                    species_name = ''
                
                # Filter by species if configured
                if not REACTOME_SPECIES or any(sp in species_name for sp in REACTOME_SPECIES):
                    processed_pathway = self._process_pathway_data(pathway)
                    if processed_pathway:
                        filtered_pathways.append(processed_pathway)
            
            return filtered_pathways
            
        except Exception as e:
            logger.error(f"Error getting pathways for {identifier}: {e}")
            return []
    
    def _process_pathway_data(self, pathway_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process raw Reactome pathway data into standardized format"""
        stable_id = pathway_data.get('stId')
        if not stable_id:
            return None
        
        # Basic pathway information
        name = pathway_data.get('displayName', '')
        description = pathway_data.get('summation', [])
        if isinstance(description, list) and description:
            description = description[0].get('text', '') if isinstance(description[0], dict) else str(description[0])
        else:
            description = str(description) if description else ''
        
        # Species information
        species_data = pathway_data.get('species', [])
        species = ''
        if isinstance(species_data, list) and species_data:
            species = species_data[0].get('displayName', '') if isinstance(species_data[0], dict) else str(species_data[0])
        species = standardize_organism_name(species)
        
        # Pathway hierarchy
        pathway_level = 0
        parent_pathway_id = None
        
        # Check if this is a sub-pathway
        if 'hasEvent' in pathway_data:
            pathway_level = 1  # Sub-pathway
        
        # Create Reactome URL
        reactome_url = create_reactome_url(stable_id)
        
        # Metadata
        metadata = {
            'source': 'Reactome',
            'db_id': pathway_data.get('dbId'),
            'schema_class': pathway_data.get('schemaClass'),
            'diagram': pathway_data.get('hasDiagram', False),
            'disease': pathway_data.get('isInDisease', False),
            'inferred': pathway_data.get('isInferred', False),
        }
        
        result = {
            'stable_id': stable_id,
            'name': name,
            'description': description,
            'species': species,
            'pathway_level': pathway_level,
            'parent_pathway_id': parent_pathway_id,
            'reactome_url': reactome_url,
            'additional_metadata': metadata
        }
        
        return result
    
    @rate_limited()
    @retry_on_failure()
    def get_pathway_participants(self, stable_id: str) -> List[Dict[str, Any]]:
        """Get participating proteins/entities in a pathway"""
        try:
            url = f"{self.base_url}/data/pathway/{stable_id}/containedEvents"
            
            response = make_throttled_request(
                url,
                endpoint_name='reactome_participants',
                headers=self.session_headers,
                timeout=REACTOME_TIMEOUT
            )
            
            events_data = response.json()
            participants = []
            
            for event in events_data:
                # Extract proteins/entities from each event
                event_participants = self._extract_event_participants(event)
                participants.extend(event_participants)
            
            # Remove duplicates based on identifier
            unique_participants = {}
            for participant in participants:
                identifier = participant.get('identifier')
                if identifier and identifier not in unique_participants:
                    unique_participants[identifier] = participant
            
            return list(unique_participants.values())
            
        except Exception as e:
            logger.error(f"Error getting participants for pathway {stable_id}: {e}")
            return []
    
    def _extract_event_participants(self, event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract participant proteins from an event"""
        participants = []
        
        # Look for input and output entities
        inputs = event_data.get('input', [])
        outputs = event_data.get('output', [])
        catalysts = event_data.get('catalystActivity', [])
        regulators = event_data.get('regulatedBy', [])
        
        all_entities = inputs + outputs
        
        # Add catalysts (enzymes)
        for catalyst in catalysts:
            if isinstance(catalyst, dict):
                catalyst_entity = catalyst.get('physicalEntity')
                if catalyst_entity:
                    all_entities.append(catalyst_entity)
        
        # Add regulators
        for regulator in regulators:
            if isinstance(regulator, dict):
                regulator_entity = regulator.get('regulator')
                if regulator_entity:
                    all_entities.append(regulator_entity)
        
        # Process each entity
        for entity in all_entities:
            if isinstance(entity, dict):
                participant = self._process_entity_data(entity)
                if participant:
                    participants.append(participant)
        
        return participants
    
    def _process_entity_data(self, entity_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process entity data to extract protein/gene information"""
        # Look for reference entity (protein, gene, etc.)
        ref_entity = entity_data.get('referenceEntity')
        if not ref_entity:
            return None
        
        # Extract identifiers
        identifier = ref_entity.get('identifier')  # Usually UniProt ID
        display_name = ref_entity.get('displayName', '')
        gene_name = ref_entity.get('geneName', [])
        
        if isinstance(gene_name, list) and gene_name:
            gene_name = gene_name[0] if isinstance(gene_name[0], str) else str(gene_name[0])
        else:
            gene_name = str(gene_name) if gene_name else ''
        
        # Extract species
        species_data = ref_entity.get('species')
        species = ''
        if isinstance(species_data, dict):
            species = species_data.get('displayName', '')
        species = standardize_organism_name(species)
        
        if identifier:
            return {
                'identifier': identifier,
                'display_name': display_name,
                'gene_name': gene_name,
                'species': species,
                'entity_type': ref_entity.get('schemaClass', ''),
                'database': ref_entity.get('databaseName', ''),
            }
        
        return None
    
    @rate_limited()
    @retry_on_failure()
    def get_pathway_hierarchy(self, stable_id: str) -> Dict[str, Any]:
        """Get pathway hierarchy information"""
        try:
            url = f"{self.base_url}/data/pathway/{stable_id}/containedEvents"
            
            response = make_throttled_request(
                url,
                endpoint_name='reactome_hierarchy',
                headers=self.session_headers,
                timeout=REACTOME_TIMEOUT
            )
            
            hierarchy_data = response.json()
            
            return {
                'stable_id': stable_id,
                'sub_pathways': [event.get('stId') for event in hierarchy_data 
                               if event.get('schemaClass') == 'Pathway'],
                'reactions': [event.get('stId') for event in hierarchy_data 
                            if event.get('schemaClass') in ['Reaction', 'BlackBoxEvent']],
                'total_events': len(hierarchy_data)
            }
            
        except Exception as e:
            logger.error(f"Error getting hierarchy for pathway {stable_id}: {e}")
            return {'stable_id': stable_id, 'sub_pathways': [], 'reactions': [], 'total_events': 0}
    
    @rate_limited()
    @retry_on_failure()
    def search_pathways(self, query: str, species: str = 'Homo sapiens') -> List[Dict[str, Any]]:
        """Search pathways by name or description"""
        try:
            url = f"{self.base_url}/data/query"
            
            params = {
                'q': query,
                'species': species,
                'types': 'Pathway'
            }
            
            response = make_throttled_request(
                url,
                endpoint_name='reactome_search',
                params=params,
                headers=self.session_headers,
                timeout=REACTOME_TIMEOUT
            )
            
            search_results = response.json()
            
            pathways = []
            for result in search_results.get('results', []):
                if result.get('schemaClass') == 'Pathway':
                    processed_pathway = self._process_pathway_data(result)
                    if processed_pathway:
                        pathways.append(processed_pathway)
            
            return pathways
            
        except Exception as e:
            logger.error(f"Error searching pathways for query '{query}': {e}")
            return []
    
    def map_targets_to_pathways(self, target_identifiers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Map multiple targets to their pathways"""
        target_pathway_mapping = {}
        
        for identifier in target_identifiers:
            try:
                # Try UniProt ID first
                pathways = self.get_pathways_for_identifier(identifier, 'uniprot')
                
                # If no results, try as gene symbol
                if not pathways:
                    pathways = self.get_pathways_for_identifier(identifier, 'gene')
                
                if pathways:
                    target_pathway_mapping[identifier] = pathways
                    logger.debug(f"Found {len(pathways)} pathways for {identifier}")
                else:
                    logger.debug(f"No pathways found for {identifier}")
                    target_pathway_mapping[identifier] = []
                    
            except Exception as e:
                logger.error(f"Error mapping {identifier} to pathways: {e}")
                target_pathway_mapping[identifier] = []
        
        return target_pathway_mapping
    
    def get_top_level_pathways(self, species: str = 'Homo sapiens') -> List[Dict[str, Any]]:
        """Get all top-level pathways for a species"""
        try:
            url = f"{self.base_url}/data/species/{species.replace(' ', '+')}/pathways"
            
            response = make_throttled_request(
                url,
                endpoint_name='reactome_top_pathways',
                headers=self.session_headers,
                timeout=REACTOME_TIMEOUT
            )
            
            pathways_data = response.json()
            
            processed_pathways = []
            for pathway in pathways_data:
                processed_pathway = self._process_pathway_data(pathway)
                if processed_pathway:
                    processed_pathway['pathway_level'] = 0  # Top level
                    processed_pathways.append(processed_pathway)
            
            return processed_pathways
            
        except Exception as e:
            logger.error(f"Error getting top-level pathways for {species}: {e}")
            return []


# Global client instance
reactome_client = ReactomeClient()
