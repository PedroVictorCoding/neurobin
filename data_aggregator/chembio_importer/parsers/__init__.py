"""Parser module initialization"""

from .chembl import ChEMBLClient, chembl_client
from .reactome import ReactomeClient, reactome_client
from .uniprot import UniProtClient, uniprot_client

__all__ = [
    'ChEMBLClient', 'chembl_client',
    'ReactomeClient', 'reactome_client', 
    'UniProtClient', 'uniprot_client'
]
