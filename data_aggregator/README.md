# ChEMBL and Reactome Cross-Importer
# A comprehensive tool for building a unified compound-target-pathway database

This tool extracts and merges compound data from ChEMBL and Reactome databases,
creating a local, structured, queryable database that maps compounds to their
targets, mechanisms, and biological pathways.

## Features

- Rate-limited API access to respect service limits
- Comprehensive compound characterization from ChEMBL
- Pathway mapping from Reactome
- Extensible database schema with SQLAlchemy
- Effect profile synthesis from mechanism and pathway data
- Batch processing with progress tracking

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Import all compounds from ChEMBL and map pathways from Reactome
python -m chembio_importer --from-chembl --from-reactome --slow

# Import specific compound
python -m chembio_importer --compound CHEMBL25 --slow

# Limit import for testing
python -m chembio_importer --from-chembl --limit 1000 --slow
```

## Database Schema

The tool creates a comprehensive database with the following main entities:
- Compounds (ChEMBL compounds with properties and synonyms)
- Targets (proteins, enzymes, receptors)
- Pathways (Reactome biological pathways)
- CompoundTargetInteractions (mechanisms and affinities)

## Configuration

Edit `chembio_importer/config.py` to customize:
- API rate limiting settings
- Database connection
- Batch sizes
- Output formats

## Architecture

```
chembio_importer/
├── __main__.py          # CLI entry point
├── config.py            # Configuration settings
├── database.py          # Database models and operations
├── models.py            # SQLAlchemy ORM models
├── throttler.py         # API rate limiting
├── utils.py             # Utility functions
└── parsers/
    ├── chembl.py        # ChEMBL API client
    ├── reactome.py      # Reactome API client
    └── uniprot.py       # UniProt API client (optional)
```
