"""
Configuration settings for ChEMBL and Reactome importer
"""
import os
from dotenv import load_dotenv

load_dotenv()

# API Settings
CHEMBL_BATCH_SIZE = 50
REACTOME_BASE_URL = "https://reactome.org/ContentService/"
UNIPROT_BASE_URL = "https://rest.uniprot.org/"
PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/"

# Rate limiting
SLOW_MODE = True
SLEEP_INTERVAL = 2  # seconds per request when slow mode is active
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# Database settings
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///chem_react.db")
DATABASE_ECHO = os.getenv("DATABASE_ECHO", "False").lower() == "true"

# Batch processing
DEFAULT_LIMIT = None  # No limit by default
PROGRESS_UPDATE_INTERVAL = 10  # Update progress every N compounds

# Output settings
EXPORT_FORMATS = ["json", "csv", "tsv"]
DEFAULT_EXPORT_DIR = "exports"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "chembio_importer.log")

# ChEMBL specific settings
CHEMBL_TIMEOUT = 30  # seconds
CHEMBL_MAX_COMPOUNDS_PER_REQUEST = 1000

# Reactome specific settings
REACTOME_TIMEOUT = 30  # seconds
REACTOME_SPECIES = ["Homo sapiens"]  # Default to human pathways

# Effect profile synthesis settings
ENABLE_EFFECT_PROFILES = True
MECHANISM_EFFECT_MAPPING = {
    "5HT2A receptor agonist": {"serotonergic": "strong activation", "psychedelic": "high"},
    "dopamine D2 receptor antagonist": {"dopaminergic": "strong inhibition", "antipsychotic": "high"},
    "SERT inhibitor": {"serotonergic": "reuptake inhibition", "antidepressant": "moderate"},
    "acetylcholinesterase inhibitor": {"cholinergic": "enhancement", "cognitive": "moderate"},
    "GABA-A receptor positive modulator": {"gabaergic": "enhancement", "anxiolytic": "high"},
}

# Data validation settings
VALIDATE_SMILES = True
VALIDATE_INCHI = True
MIN_MOLECULAR_WEIGHT = 50  # Da
MAX_MOLECULAR_WEIGHT = 2000  # Da
