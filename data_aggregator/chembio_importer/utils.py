"""
Utility functions for data processing and validation
"""
import re
import json
import logging
from typing import Dict, List, Any, Optional, Union
from rdkit import Chem
from rdkit.Chem import Descriptors, Crippen, Lipinski

from .config import (
    VALIDATE_SMILES, VALIDATE_INCHI, MIN_MOLECULAR_WEIGHT, MAX_MOLECULAR_WEIGHT,
    MECHANISM_EFFECT_MAPPING, ENABLE_EFFECT_PROFILES
)

logger = logging.getLogger(__name__)


def validate_smiles(smiles: str) -> bool:
    """Validate SMILES string using RDKit"""
    if not VALIDATE_SMILES or not smiles:
        return True
    
    try:
        mol = Chem.MolFromSmiles(smiles)
        return mol is not None
    except Exception as e:
        logger.debug(f"Invalid SMILES {smiles}: {e}")
        return False


def validate_inchi(inchi: str) -> bool:
    """Validate InChI string using RDKit"""
    if not VALIDATE_INCHI or not inchi:
        return True
    
    try:
        mol = Chem.MolFromInchi(inchi)
        return mol is not None
    except Exception as e:
        logger.debug(f"Invalid InChI {inchi}: {e}")
        return False


def calculate_molecular_properties(smiles: str) -> Dict[str, float]:
    """Calculate molecular properties from SMILES"""
    if not smiles:
        return {}
    
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {}
        
        properties = {
            'molecular_weight': Descriptors.MolWt(mol),
            'logp': Crippen.MolLogP(mol),
            'tpsa': Descriptors.TPSA(mol),
            'hbd': Descriptors.NumHDonors(mol),
            'hba': Descriptors.NumHAcceptors(mol),
            'rotatable_bonds': Descriptors.NumRotatableBonds(mol),
            'aromatic_rings': Descriptors.NumAromaticRings(mol),
            'aliphatic_rings': Descriptors.NumAliphaticRings(mol),
        }
        
        return properties
    except Exception as e:
        logger.error(f"Error calculating properties for SMILES {smiles}: {e}")
        return {}


def validate_molecular_weight(mw: float) -> bool:
    """Validate molecular weight is within reasonable range"""
    if mw is None:
        return True
    return MIN_MOLECULAR_WEIGHT <= mw <= MAX_MOLECULAR_WEIGHT


def normalize_activity_value(value: Union[str, float], units: str) -> Optional[float]:
    """Normalize activity values to standard units (nM)"""
    if value is None or value == '':
        return None
    
    try:
        # Convert to float if string
        if isinstance(value, str):
            # Handle scientific notation and special characters
            value = value.replace(',', '').strip()
            if value.startswith('>') or value.startswith('<') or value.startswith('~'):
                value = value[1:].strip()
            value = float(value)
        
        # Convert to nM based on units
        units = units.lower() if units else 'nm'
        
        conversion_factors = {
            'nm': 1.0,
            'um': 1000.0,
            'mm': 1000000.0,
            'μm': 1000.0,  # Greek mu
            'µm': 1000.0,  # Micro sign
            'm': 1000000000.0,
            'pm': 0.001,
        }
        
        for unit, factor in conversion_factors.items():
            if unit in units:
                return value * factor
        
        # Default to assuming nM if unit not recognized
        logger.warning(f"Unknown unit '{units}', assuming nM")
        return value
        
    except (ValueError, TypeError) as e:
        logger.error(f"Error normalizing activity value '{value}' with units '{units}': {e}")
        return None


def clean_compound_name(name: str) -> str:
    """Clean and standardize compound names"""
    if not name:
        return ""
    
    # Remove extra whitespace
    name = ' '.join(name.split())
    
    # Remove common prefixes/suffixes that don't add information
    prefixes_to_remove = ['compound ', 'drug ', 'molecule ']
    suffixes_to_remove = [' compound', ' drug', ' molecule']
    
    name_lower = name.lower()
    for prefix in prefixes_to_remove:
        if name_lower.startswith(prefix):
            name = name[len(prefix):]
            break
    
    for suffix in suffixes_to_remove:
        if name_lower.endswith(suffix):
            name = name[:-len(suffix)]
            break
    
    return name.strip()


def extract_gene_symbol(target_name: str) -> Optional[str]:
    """Extract gene symbol from target name"""
    if not target_name:
        return None
    
    # Look for gene symbols in parentheses
    match = re.search(r'\(([A-Z0-9]+)\)', target_name)
    if match:
        return match.group(1)
    
    # Look for gene symbols at the beginning
    match = re.search(r'^([A-Z0-9]+)\s', target_name)
    if match:
        return match.group(1)
    
    return None


def generate_effect_profile(mechanisms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate effect profile from compound mechanisms"""
    if not ENABLE_EFFECT_PROFILES or not mechanisms:
        return {}
    
    effect_profile = {}
    
    for mechanism_data in mechanisms:
        mechanism = mechanism_data.get('mechanism', '').lower()
        target_name = mechanism_data.get('target_name', '').lower()
        affinity = mechanism_data.get('activity_value')
        
        # Create mechanism description
        full_mechanism = f"{target_name} {mechanism}".strip()
        
        # Look for known effect mappings
        for known_mechanism, effects in MECHANISM_EFFECT_MAPPING.items():
            if known_mechanism.lower() in full_mechanism:
                for effect_type, effect_strength in effects.items():
                    if effect_type not in effect_profile:
                        effect_profile[effect_type] = effect_strength
                    else:
                        # Combine effects (simple approach - take strongest)
                        current = effect_profile[effect_type]
                        if isinstance(current, str) and isinstance(effect_strength, str):
                            # Simple precedence: high > moderate > low
                            precedence = {'high': 3, 'strong': 3, 'moderate': 2, 'weak': 1, 'low': 1}
                            if precedence.get(effect_strength, 0) > precedence.get(current, 0):
                                effect_profile[effect_type] = effect_strength
                break
        
        # Add mechanism-specific information
        if mechanism and target_name:
            mechanism_key = f"{target_name}_modulation"
            effect_profile[mechanism_key] = mechanism
    
    return effect_profile


def parse_chembl_activity_relation(relation: str) -> str:
    """Parse and standardize ChEMBL activity relation symbols"""
    if not relation:
        return "="
    
    relation_mapping = {
        "'='": "=",
        "'<'": "<",
        "'>'": ">",
        "'<='": "<=",
        "'>='": ">=",
        "'~'": "~",
        "=": "=",
        "<": "<",
        ">": ">",
        "<=": "<=",
        ">=": ">=",
        "~": "~",
    }
    
    return relation_mapping.get(relation, "=")


def create_reactome_url(stable_id: str) -> str:
    """Create Reactome URL from stable ID"""
    if not stable_id:
        return ""
    return f"https://reactome.org/content/detail/{stable_id}"


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """Safely parse JSON string, returning default on error"""
    if not json_str:
        return default
    
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"Error parsing JSON: {e}")
        return default


def safe_json_dumps(obj: Any, default: str = "{}") -> str:
    """Safely serialize object to JSON string"""
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing to JSON: {e}")
        return default


def batch_list(items: List[Any], batch_size: int) -> List[List[Any]]:
    """Split a list into batches of specified size"""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def merge_dictionaries(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple dictionaries, with later ones taking precedence"""
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def filter_empty_values(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys with None, empty string, or empty list values"""
    return {k: v for k, v in data.items() 
            if v is not None and v != "" and v != [] and v != {}}


def standardize_organism_name(organism: str) -> str:
    """Standardize organism names"""
    if not organism:
        return ""
    
    organism_mapping = {
        'homo sapiens': 'Homo sapiens',
        'human': 'Homo sapiens',
        'mus musculus': 'Mus musculus',
        'mouse': 'Mus musculus',
        'rattus norvegicus': 'Rattus norvegicus',
        'rat': 'Rattus norvegicus',
    }
    
    return organism_mapping.get(organism.lower(), organism.title())


def log_data_quality_issues(data: Dict[str, Any], entity_type: str, entity_id: str):
    """Log data quality issues for monitoring"""
    issues = []
    
    if entity_type == 'compound':
        if not data.get('name'):
            issues.append("missing_name")
        if not data.get('canonical_smiles'):
            issues.append("missing_smiles")
        if data.get('molecular_weight') and not validate_molecular_weight(data['molecular_weight']):
            issues.append("invalid_molecular_weight")
    
    elif entity_type == 'target':
        if not data.get('name'):
            issues.append("missing_name")
        if not data.get('gene_symbol'):
            issues.append("missing_gene_symbol")
        if not data.get('organism'):
            issues.append("missing_organism")
    
    elif entity_type == 'interaction':
        if not data.get('mechanism'):
            issues.append("missing_mechanism")
        if not data.get('activity_value'):
            issues.append("missing_activity_value")
    
    if issues:
        logger.debug(f"Data quality issues for {entity_type} {entity_id}: {', '.join(issues)}")
    
    return issues
