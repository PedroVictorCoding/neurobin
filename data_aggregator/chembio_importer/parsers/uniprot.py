"""
UniProt API client for protein data retrieval (optional component)
"""
import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin

from ..config import UNIPROT_BASE_URL
from ..throttler import make_throttled_request, rate_limited, retry_on_failure
from ..utils import standardize_organism_name, extract_gene_symbol

logger = logging.getLogger(__name__)


class UniProtClient:
    """UniProt API client for protein metadata retrieval"""
    
    def __init__(self, base_url: str = UNIPROT_BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.session_headers = {
            'Accept': 'application/json',
            'User-Agent': 'ChemBio-Importer/1.0'
        }
    
    @rate_limited()
    @retry_on_failure()
    def get_protein_by_uniprot_id(self, uniprot_id: str) -> Optional[Dict[str, Any]]:
        """Get protein information by UniProt ID"""
        try:
            url = f"{self.base_url}/uniprotkb/{uniprot_id}"
            
            response = make_throttled_request(
                url,
                endpoint_name='uniprot_protein',
                headers=self.session_headers,
                timeout=30
            )
            
            protein_data = response.json()
            return self._process_protein_data(protein_data)
            
        except Exception as e:
            logger.error(f"Error getting protein {uniprot_id}: {e}")
            return None
    
    def _process_protein_data(self, protein_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process raw UniProt protein data into standardized format"""
        # Basic information
        accession = protein_data.get('primaryAccession', '')
        
        # Protein names
        protein_description = protein_data.get('proteinDescription', {})
        recommended_name = protein_description.get('recommendedName', {})
        full_name = recommended_name.get('fullName', {}).get('value', '')
        
        # Alternative names
        alternative_names = []
        alt_names = protein_description.get('alternativeNames', [])
        for alt_name in alt_names:
            if isinstance(alt_name, dict):
                alt_full_name = alt_name.get('fullName', {}).get('value')
                if alt_full_name:
                    alternative_names.append(alt_full_name)
        
        # Gene information
        genes = protein_data.get('genes', [])
        gene_name = ''
        gene_synonyms = []
        
        if genes:
            primary_gene = genes[0] if isinstance(genes[0], dict) else {}
            gene_name = primary_gene.get('geneName', {}).get('value', '')
            
            # Gene synonyms
            gene_synonyms_data = primary_gene.get('synonyms', [])
            for synonym in gene_synonyms_data:
                if isinstance(synonym, dict):
                    syn_value = synonym.get('value')
                    if syn_value:
                        gene_synonyms.append(syn_value)
        
        # Organism
        organism_data = protein_data.get('organism', {})
        organism_name = organism_data.get('scientificName', '')
        tax_id = organism_data.get('taxonId')
        
        # Protein features and domains
        features = protein_data.get('features', [])
        domains = []
        for feature in features:
            if isinstance(feature, dict) and feature.get('type') == 'domain':
                domain_desc = feature.get('description')
                if domain_desc:
                    domains.append(domain_desc)
        
        # Subcellular location
        subcellular_locations = []
        comments = protein_data.get('comments', [])
        for comment in comments:
            if isinstance(comment, dict) and comment.get('commentType') == 'SUBCELLULAR_LOCATION':
                locations = comment.get('subcellularLocations', [])
                for location in locations:
                    if isinstance(location, dict):
                        location_name = location.get('location', {}).get('value')
                        if location_name:
                            subcellular_locations.append(location_name)
        
        # Function description
        function_description = ''
        for comment in comments:
            if isinstance(comment, dict) and comment.get('commentType') == 'FUNCTION':
                function_texts = comment.get('texts', [])
                if function_texts:
                    function_description = function_texts[0].get('value', '')
                break
        
        # Cross-references
        cross_references = {}
        uniprotkb_cross_refs = protein_data.get('uniProtKBCrossReferences', [])
        for ref in uniprotkb_cross_refs:
            if isinstance(ref, dict):
                database = ref.get('database')
                ref_id = ref.get('id')
                if database and ref_id:
                    if database not in cross_references:
                        cross_references[database] = []
                    cross_references[database].append(ref_id)
        
        # Sequence information
        sequence_data = protein_data.get('sequence', {})
        sequence_length = sequence_data.get('length')
        molecular_weight = sequence_data.get('molWeight')
        
        result = {
            'uniprot_id': accession,
            'protein_name': full_name,
            'alternative_names': alternative_names,
            'gene_name': gene_name,
            'gene_synonyms': gene_synonyms,
            'organism': standardize_organism_name(organism_name),
            'tax_id': tax_id,
            'function_description': function_description,
            'domains': domains,
            'subcellular_locations': subcellular_locations,
            'sequence_length': sequence_length,
            'molecular_weight': molecular_weight,
            'cross_references': cross_references,
            'additional_metadata': {
                'source': 'UniProt',
                'entry_type': protein_data.get('entryType'),
                'entry_audit': protein_data.get('entryAudit', {}),
            }
        }
        
        return result
    
    @rate_limited()
    @retry_on_failure()
    def search_proteins(self, query: str, organism: str = 'human', 
                       limit: int = 100) -> List[Dict[str, Any]]:
        """Search proteins by query string"""
        try:
            # Construct search query
            search_query = f"{query}"
            if organism:
                if organism.lower() == 'human':
                    search_query += " AND organism_id:9606"
                else:
                    search_query += f" AND organism_name:{organism}"
            
            url = f"{self.base_url}/uniprotkb/search"
            params = {
                'query': search_query,
                'size': limit,
                'fields': 'accession,protein_name,gene_names,organism_name'
            }
            
            response = make_throttled_request(
                url,
                endpoint_name='uniprot_search',
                params=params,
                headers=self.session_headers,
                timeout=30
            )
            
            search_results = response.json()
            
            proteins = []
            for result in search_results.get('results', []):
                processed_protein = self._process_search_result(result)
                if processed_protein:
                    proteins.append(processed_protein)
            
            return proteins
            
        except Exception as e:
            logger.error(f"Error searching proteins for query '{query}': {e}")
            return []
    
    def _process_search_result(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process search result into simplified format"""
        accession = result_data.get('primaryAccession', '')
        
        # Protein name
        protein_description = result_data.get('proteinDescription', {})
        recommended_name = protein_description.get('recommendedName', {})
        protein_name = recommended_name.get('fullName', {}).get('value', '')
        
        # Gene name
        genes = result_data.get('genes', [])
        gene_name = ''
        if genes:
            primary_gene = genes[0] if isinstance(genes[0], dict) else {}
            gene_name = primary_gene.get('geneName', {}).get('value', '')
        
        # Organism
        organism_data = result_data.get('organism', {})
        organism_name = organism_data.get('scientificName', '')
        
        return {
            'uniprot_id': accession,
            'protein_name': protein_name,
            'gene_name': gene_name,
            'organism': standardize_organism_name(organism_name),
        }
    
    def map_gene_symbols_to_uniprot(self, gene_symbols: List[str], 
                                   organism: str = 'human') -> Dict[str, str]:
        """Map gene symbols to UniProt IDs"""
        mapping = {}
        
        for gene_symbol in gene_symbols:
            try:
                # Search for the gene symbol
                results = self.search_proteins(f"gene:{gene_symbol}", organism, limit=1)
                
                if results:
                    uniprot_id = results[0].get('uniprot_id')
                    if uniprot_id:
                        mapping[gene_symbol] = uniprot_id
                        logger.debug(f"Mapped {gene_symbol} to {uniprot_id}")
                    else:
                        logger.debug(f"No UniProt ID found for {gene_symbol}")
                else:
                    logger.debug(f"No results found for gene symbol {gene_symbol}")
                    
            except Exception as e:
                logger.error(f"Error mapping gene symbol {gene_symbol}: {e}")
        
        return mapping
    
    def enrich_target_data(self, target_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich target data with UniProt information"""
        uniprot_id = target_data.get('uniprot_id')
        if not uniprot_id:
            # Try to find UniProt ID by gene symbol
            gene_symbol = target_data.get('gene_symbol')
            if gene_symbol:
                mapping = self.map_gene_symbols_to_uniprot([gene_symbol])
                uniprot_id = mapping.get(gene_symbol)
                if uniprot_id:
                    target_data['uniprot_id'] = uniprot_id
        
        if uniprot_id:
            # Get detailed protein information
            protein_info = self.get_protein_by_uniprot_id(uniprot_id)
            if protein_info:
                # Merge UniProt data with existing target data
                enriched_data = target_data.copy()
                
                # Update/add fields from UniProt
                if not enriched_data.get('description') and protein_info.get('function_description'):
                    enriched_data['description'] = protein_info['function_description']
                
                # Add UniProt-specific metadata
                if 'additional_metadata' not in enriched_data:
                    enriched_data['additional_metadata'] = {}
                
                enriched_data['additional_metadata'].update({
                    'uniprot_protein_name': protein_info.get('protein_name'),
                    'uniprot_alternative_names': protein_info.get('alternative_names'),
                    'domains': protein_info.get('domains'),
                    'subcellular_locations': protein_info.get('subcellular_locations'),
                    'sequence_length': protein_info.get('sequence_length'),
                    'cross_references': protein_info.get('cross_references'),
                })
                
                return enriched_data
        
        return target_data


# Global client instance
uniprot_client = UniProtClient()
