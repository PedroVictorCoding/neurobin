"""
ChEMBL and Reactome Cross-Importer Package
"""

__version__ = "1.0.0"
__author__ = "ChemBio Importer"
__description__ = "A comprehensive tool for importing and cross-referencing compound data from ChEMBL and Reactome"

from .database import db_manager
from .parsers import chembl_client, reactome_client, uniprot_client

__all__ = [
    'db_manager',
    'chembl_client', 
    'reactome_client',
    'uniprot_client'
]
