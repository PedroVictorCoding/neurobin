"""
Main CLI interface for ChEMBL and Reactome data importer
"""
import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import click
from tqdm import tqdm

from .config import (
    DATABASE_URL, LOG_LEVEL, LOG_FILE, SLOW_MODE, DEFAULT_LIMIT,
    PROGRESS_UPDATE_INTERVAL, DEFAULT_EXPORT_DIR
)
from .database import db_manager
from .parsers import chembl_client, reactome_client, uniprot_client
from .utils import generate_effect_profile, merge_dictionaries, filter_empty_values

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ChemBioImporter:
    """Main importer class coordinating data import from multiple sources"""
    
    def __init__(self):
        self.db_manager = db_manager
        self.chembl_client = chembl_client
        self.reactome_client = reactome_client
        self.uniprot_client = uniprot_client
        
        # Statistics tracking
        self.stats = {
            'compounds_processed': 0,
            'compounds_created': 0,
            'compounds_updated': 0,
            'targets_processed': 0,
            'targets_created': 0,
            'pathways_processed': 0,
            'pathways_created': 0,
            'interactions_created': 0,
            'errors': 0
        }
    
    def initialize_database(self):
        """Initialize database tables"""
        logger.info("Initializing database...")
        self.db_manager.create_tables()
        logger.info("Database initialized successfully")
    
    def import_from_chembl(self, limit: Optional[int] = None, specific_compound: Optional[str] = None):
        """Import compounds and targets from ChEMBL"""
        logger.info("Starting ChEMBL import...")
        
        with self.db_manager.get_session() as session:
            # Log import operation
            import_log = self.db_manager.log_import_operation(
                session, 'chembl_import', 'started',
                started_at=datetime.now(),
                parameters={'limit': limit, 'specific_compound': specific_compound}
            )
            
            try:
                if specific_compound:
                    # Import specific compound
                    self._import_specific_compound(session, specific_compound)
                else:
                    # Import all compounds
                    self._import_all_compounds(session, limit)
                
                # Update import log
                import_log.status = 'completed'
                import_log.completed_at = datetime.now()
                import_log.duration_seconds = (import_log.completed_at - import_log.started_at).total_seconds()
                import_log.records_processed = self.stats['compounds_processed']
                import_log.records_imported = self.stats['compounds_created']
                import_log.records_updated = self.stats['compounds_updated']
                import_log.summary = self.stats.copy()
                
                logger.info(f"ChEMBL import completed. Processed {self.stats['compounds_processed']} compounds")
                
            except Exception as e:
                import_log.status = 'failed'
                import_log.error_message = str(e)
                import_log.completed_at = datetime.now()
                logger.error(f"ChEMBL import failed: {e}")
                raise
    
    def _import_specific_compound(self, session, chembl_id: str):
        """Import a specific compound with all its data"""
        logger.info(f"Importing specific compound: {chembl_id}")
        
        # Get comprehensive compound data
        compound_data = self.chembl_client.get_compound_with_targets_and_mechanisms(chembl_id)
        if not compound_data:
            logger.error(f"Could not retrieve data for compound {chembl_id}")
            return
        
        # Import compound
        compound, created = self._import_compound_data(session, compound_data)
        
        # Import targets and interactions
        target_interactions = compound_data.get('target_interactions', [])
        for interaction_data in target_interactions:
            self._import_target_interaction(session, compound, interaction_data)
        
        # Generate and store effect profile
        mechanisms = compound_data.get('mechanisms', [])
        if mechanisms:
            effect_profile = generate_effect_profile(mechanisms)
            if effect_profile:
                compound.effect_profile = effect_profile
        
        self.stats['compounds_processed'] += 1
        if created:
            self.stats['compounds_created'] += 1
        else:
            self.stats['compounds_updated'] += 1
        
        session.commit()
        logger.info(f"Successfully imported compound {chembl_id}")
    
    def _import_all_compounds(self, session, limit: Optional[int]):
        """Import all compounds from ChEMBL with complete target and mechanism data"""
        effective_limit = limit or DEFAULT_LIMIT
        logger.info(f"Importing compounds from ChEMBL (limit: {effective_limit or 'unlimited'})")
        
        # Get compound iterator
        compound_iterator = self.chembl_client.get_all_compounds(
            limit=effective_limit,
            progress_callback=self._progress_callback
        )
        
        compound_count = 0
        
        for compound_data in compound_iterator:
            try:
                # Import compound with all its data
                self._import_complete_compound(session, compound_data)
                compound_count += 1
                
                # Commit after each compound to save progress
                session.commit()
                
                # Log progress periodically
                if compound_count % 10 == 0:
                    logger.info(f"Processed {compound_count} compounds so far...")
                    
            except Exception as e:
                logger.error(f"Error processing compound {compound_data.get('chembl_id')}: {e}")
                self.stats['errors'] += 1
                # Rollback this compound but continue with next
                session.rollback()
        
        logger.info(f"Completed import of {compound_count} compounds")
    
    def _import_complete_compound(self, session, compound_data: Dict[str, Any]):
        """Import a single compound with all its targets, mechanisms, and pathways"""
        chembl_id = compound_data.get('chembl_id')
        if not chembl_id:
            return
        
        # Skip compounds with no name or with CHEMBL in the name
        compound_name = compound_data.get('pref_name')
        logger.debug(f"Compound {chembl_id} name: '{compound_name}'")
        if not compound_name or 'CHEMBL' in compound_name.upper():
            logger.info(f"Skipping compound {chembl_id} - no name or contains CHEMBL: {compound_name}")
            return
        
        logger.info(f"Importing complete data for compound {chembl_id}")
        
        # Step 1: Import the compound itself
        compound, created = self._import_compound_data(session, compound_data)
        
        if created:
            self.stats['compounds_created'] += 1
        else:
            self.stats['compounds_updated'] += 1
        self.stats['compounds_processed'] += 1
        
        # Step 2: Get and import all target interactions for this compound
        try:
            target_interactions = self.chembl_client.get_compound_targets(chembl_id)
            logger.info(f"Found {len(target_interactions)} target interactions for {chembl_id}")
            
            # Filter to only human targets
            human_interactions = []
            for interaction_data in target_interactions:
                target_chembl_id = interaction_data.get('target_chembl_id')
                if target_chembl_id:
                    # Get target details to check organism
                    target_info = self.chembl_client.get_target_by_id(target_chembl_id)
                    if target_info and self._is_human_target(target_info):
                        human_interactions.append(interaction_data)
                        logger.debug(f"Including human target: {target_chembl_id}")
                    else:
                        logger.debug(f"Skipping non-human target: {target_chembl_id}")
            
            logger.info(f"Filtered to {len(human_interactions)} human target interactions for {chembl_id}")
            
            for interaction_data in human_interactions:
                try:
                    target = self._import_target_interaction(session, compound, interaction_data)
                    if target:
                        # Map target to pathways if it has UniProt ID
                        if target.uniprot_id:
                            self._map_target_to_pathways(session, target)
                except Exception as e:
                    logger.error(f"Error importing target interaction for {chembl_id}: {e}")
        
        except Exception as e:
            logger.error(f"Error getting targets for compound {chembl_id}: {e}")
        
        # Step 3: Get and import mechanisms of action (filter to human targets)
        try:
            mechanisms = self.chembl_client.get_compound_mechanisms(chembl_id)
            logger.info(f"Found {len(mechanisms)} mechanisms for {chembl_id}")
            
            # Filter mechanisms to human targets only
            human_mechanisms = []
            for mechanism_data in mechanisms:
                target_chembl_id = mechanism_data.get('target_chembl_id')
                if target_chembl_id:
                    target_info = self.chembl_client.get_target_by_id(target_chembl_id)
                    if target_info and self._is_human_target(target_info):
                        human_mechanisms.append(mechanism_data)
            
            logger.info(f"Filtered to {len(human_mechanisms)} human mechanisms for {chembl_id}")
            
            if human_mechanisms:
                # Generate effect profile from human mechanisms only
                effect_profile = self._generate_compound_effect_profile(human_mechanisms, human_interactions)
                if effect_profile:
                    compound.effect_profile = effect_profile
                    logger.info(f"Generated effect profile for {chembl_id}: {effect_profile}")
        
        except Exception as e:
            logger.error(f"Error getting mechanisms for compound {chembl_id}: {e}")
        
        logger.info(f"✓ Completed import of compound {chembl_id}")
    
    def _map_target_to_pathways(self, session, target):
        """Map a single target to its human pathways only"""
        try:
            pathways_data = self.reactome_client.get_pathways_for_identifier(target.uniprot_id, 'uniprot')
            
            for pathway_data in pathways_data:
                # Only include human pathways
                if pathway_data.get('species') == 'Homo sapiens':
                    try:
                        pathway, created = self.db_manager.get_or_create_pathway(
                            session, **filter_empty_values(pathway_data)
                        )
                        
                        # Link target to pathway if not already linked
                        if pathway not in target.pathways:
                            target.pathways.append(pathway)
                            logger.debug(f"Linked target {target.gene_symbol} to human pathway {pathway.name}")
                        
                        if created:
                            self.stats['pathways_created'] += 1
                        self.stats['pathways_processed'] += 1
                    
                    except Exception as e:
                        logger.error(f"Error creating pathway {pathway_data.get('stable_id')}: {e}")
                else:
                    logger.debug(f"Skipping non-human pathway: {pathway_data.get('name')} ({pathway_data.get('species')})")
        
        except Exception as e:
            logger.error(f"Error mapping target {target.uniprot_id} to pathways: {e}")
    
    def _generate_compound_effect_profile(self, mechanisms: List[Dict], interactions: List[Dict]) -> Dict[str, Any]:
        """Generate effect profile from mechanisms and interactions"""
        try:
            from .utils import generate_effect_profile
            
            # Combine mechanism and interaction data
            combined_data = []
            
            # Add mechanism data
            for mech in mechanisms:
                combined_data.append({
                    'mechanism': mech.get('mechanism'),
                    'target_name': mech.get('target_name', ''),
                    'activity_value': None
                })
            
            # Add interaction data with affinities
            for interaction in interactions:
                combined_data.append({
                    'mechanism': interaction.get('activity_type', ''),
                    'target_name': interaction.get('target_name', ''),
                    'activity_value': interaction.get('activity_value')
                })
            
            return generate_effect_profile(combined_data)
        
        except Exception as e:
            logger.error(f"Error generating effect profile: {e}")
            return {}
    
    def _process_compound_batch(self, session, compounds_batch):
        """Process a batch of compounds with complete data import"""
        for compound_data in compounds_batch:
            try:
                # Import compound with all its related data
                self._import_complete_compound_data(session, compound_data)
                
                self.stats['compounds_processed'] += 1
                
            except Exception as e:
                logger.error(f"Error processing compound {compound_data.get('chembl_id')}: {e}")
                self.stats['errors'] += 1
    
    def _import_complete_compound_data(self, session, compound_data: Dict[str, Any]):
        """Import compound with all targets, mechanisms, and pathways"""
        chembl_id = compound_data['chembl_id']
        logger.info(f"Importing complete data for compound {chembl_id}")
        
        # Import the compound itself
        compound, created = self._import_compound_data(session, compound_data)
        
        if created:
            self.stats['compounds_created'] += 1
        else:
            self.stats['compounds_updated'] += 1
        
        # Get targets and interactions for this compound
        logger.debug(f"Fetching targets for {chembl_id}")
        target_interactions = self.chembl_client.get_compound_targets(chembl_id)
        
        # Filter targets to Homo sapiens only
        human_interactions = []
        for interaction_data in target_interactions:
            target_chembl_id = interaction_data.get('target_chembl_id')
            if target_chembl_id:
                # Get target details to check organism
                target_info = self.chembl_client.get_target_by_id(target_chembl_id)
                if target_info and self._is_human_target(target_info):
                    human_interactions.append(interaction_data)
                    logger.debug(f"Including human target: {target_chembl_id}")
                else:
                    logger.debug(f"Skipping non-human target: {target_chembl_id}")
        
        # Import human target interactions
        for interaction_data in human_interactions:
            try:
                target = self._import_target_interaction(session, compound, interaction_data)
                if target:
                    # Import pathways for this target
                    self._import_target_pathways(session, target)
            except Exception as e:
                logger.error(f"Error importing interaction for {chembl_id}: {e}")
        
        # Get mechanisms for this compound
        logger.debug(f"Fetching mechanisms for {chembl_id}")
        mechanisms = self.chembl_client.get_compound_mechanisms(chembl_id)
        
        # Filter mechanisms to human targets only
        human_mechanisms = []
        for mechanism_data in mechanisms:
            target_chembl_id = mechanism_data.get('target_chembl_id')
            if target_chembl_id:
                target_info = self.chembl_client.get_target_by_id(target_chembl_id)
                if target_info and self._is_human_target(target_info):
                    human_mechanisms.append(mechanism_data)
        
        # Generate and store effect profile from human mechanisms
        if human_mechanisms:
            effect_profile = generate_effect_profile(human_mechanisms)
            if effect_profile:
                compound.effect_profile = effect_profile
                logger.debug(f"Generated effect profile for {chembl_id}: {effect_profile}")
        
        # Commit after each compound to ensure data persistence
        session.commit()
        logger.info(f"Completed import for compound {chembl_id} with {len(human_interactions)} targets and {len(human_mechanisms)} mechanisms")
    
    def _import_compound_data(self, session, compound_data: Dict[str, Any]) -> tuple:
        """Import compound data into database"""
        chembl_id = compound_data['chembl_id']
        
        # Separate synonyms from main compound data
        synonyms_data = compound_data.pop('synonyms', [])
        
        # Clean compound data
        clean_data = filter_empty_values(compound_data)
        clean_data['additional_metadata']['import_date'] = datetime.now().isoformat()
        
        # Create or update compound
        compound, created = self.db_manager.get_or_create_compound(session, **clean_data)
        
        # Add synonyms
        for synonym_data in synonyms_data:
            synonym, _ = self.db_manager.get_or_create_synonym(
                session,
                name=synonym_data['name'],
                synonym_type=synonym_data.get('type'),
                source=synonym_data.get('source', 'ChEMBL')
            )
            if synonym not in compound.synonyms:
                compound.synonyms.append(synonym)
        
        return compound, created
    
    def _import_target_interaction(self, session, compound, interaction_data: Dict[str, Any]):
        """Import compound-target interaction and return the target"""
        target_chembl_id = interaction_data.get('target_chembl_id')
        if not target_chembl_id:
            return None
        
        # Get or create target
        target_info = self.chembl_client.get_target_by_id(target_chembl_id)
        if not target_info:
            logger.warning(f"Could not retrieve target data for {target_chembl_id}")
            return None
        
        # Enrich with UniProt data if available
        enriched_target_info = self.uniprot_client.enrich_target_data(target_info)
        
        target, target_created = self.db_manager.get_or_create_target(
            session, **filter_empty_values(enriched_target_info)
        )
        
        if target_created:
            self.stats['targets_created'] += 1
        self.stats['targets_processed'] += 1
        
        # Create interaction with target name for effect profile
        interaction_data_clean = {k: v for k, v in interaction_data.items() 
                                if k not in ['target_chembl_id'] and v is not None}
        
        # Add target name for effect profile generation
        interaction_data_clean['target_name'] = target.name or target.gene_symbol or ''
        
        interaction = self.db_manager.create_compound_target_interaction(
            session, compound, target, **interaction_data_clean
        )
        
        self.stats['interactions_created'] += 1
        
        return target
    
    def _is_human_target(self, target_info: Dict[str, Any]) -> bool:
        """Check if target is from Homo sapiens"""
        organism = target_info.get('organism', '').lower()
        return 'homo sapiens' in organism or 'human' in organism
    
    def _import_target_pathways(self, session, target):
        """Import pathways for a specific target"""
        if not target.uniprot_id:
            return
        
        try:
            # Get pathways for this target
            pathways_data = self.reactome_client.get_pathways_for_identifier(target.uniprot_id, 'uniprot')
            
            for pathway_data in pathways_data:
                # Only import human pathways
                if pathway_data.get('species') == 'Homo sapiens':
                    pathway, created = self.db_manager.get_or_create_pathway(
                        session, **filter_empty_values(pathway_data)
                    )
                    
                    # Link target to pathway
                    if pathway not in target.pathways:
                        target.pathways.append(pathway)
                        logger.debug(f"Linked target {target.chembl_id} to pathway {pathway.stable_id}")
                    
                    if created:
                        self.stats['pathways_created'] += 1
                    self.stats['pathways_processed'] += 1
                        
        except Exception as e:
            logger.debug(f"Could not import pathways for target {target.chembl_id}: {e}")
    
    def import_pathways_from_reactome(self, targets_only: bool = True):
        """Import pathways from Reactome, optionally limited to targets in database"""
        logger.info("Starting Reactome pathway import...")
        
        with self.db_manager.get_session() as session:
            import_log = self.db_manager.log_import_operation(
                session, 'reactome_import', 'started',
                started_at=datetime.now(),
                parameters={'targets_only': targets_only}
            )
            
            try:
                if targets_only:
                    self._import_pathways_for_existing_targets(session)
                else:
                    self._import_all_pathways(session)
                
                # Update import log
                import_log.status = 'completed'
                import_log.completed_at = datetime.now()
                import_log.duration_seconds = (import_log.completed_at - import_log.started_at).total_seconds()
                import_log.records_processed = self.stats['pathways_processed']
                import_log.records_imported = self.stats['pathways_created']
                import_log.summary = self.stats.copy()
                
                logger.info(f"Reactome import completed. Processed {self.stats['pathways_processed']} pathways")
                
            except Exception as e:
                import_log.status = 'failed'
                import_log.error_message = str(e)
                import_log.completed_at = datetime.now()
                logger.error(f"Reactome import failed: {e}")
                raise
    
    def _import_pathways_for_existing_targets(self, session):
        """Import pathways for targets already in database"""
        from .models import Target
        
        # Get all targets with UniProt IDs
        targets = session.query(Target).filter(Target.uniprot_id.isnot(None)).all()
        logger.info(f"Found {len(targets)} targets with UniProt IDs")
        
        uniprot_ids = [target.uniprot_id for target in targets]
        
        # Map targets to pathways
        target_pathway_mapping = self.reactome_client.map_targets_to_pathways(uniprot_ids)
        
        for target in targets:
            if target.uniprot_id in target_pathway_mapping:
                pathways_data = target_pathway_mapping[target.uniprot_id]
                
                for pathway_data in pathways_data:
                    # Create or update pathway
                    pathway, created = self.db_manager.get_or_create_pathway(
                        session, **filter_empty_values(pathway_data)
                    )
                    
                    # Link target to pathway
                    if pathway not in target.pathways:
                        target.pathways.append(pathway)
                    
                    if created:
                        self.stats['pathways_created'] += 1
                    self.stats['pathways_processed'] += 1
        
        session.commit()
    
    def _import_all_pathways(self, session):
        """Import all top-level pathways from Reactome"""
        pathways = self.reactome_client.get_top_level_pathways()
        logger.info(f"Found {len(pathways)} top-level pathways")
        
        for pathway_data in pathways:
            try:
                pathway, created = self.db_manager.get_or_create_pathway(
                    session, **filter_empty_values(pathway_data)
                )
                
                if created:
                    self.stats['pathways_created'] += 1
                self.stats['pathways_processed'] += 1
                
            except Exception as e:
                logger.error(f"Error importing pathway {pathway_data.get('stable_id')}: {e}")
                self.stats['errors'] += 1
        
        session.commit()
    
    def _progress_callback(self, current: int, total: int):
        """Progress callback for long-running operations"""
        if current % PROGRESS_UPDATE_INTERVAL == 0:
            percentage = (current / total) * 100 if total > 0 else 0
            logger.info(f"Progress: {current}/{total} ({percentage:.1f}%)")
    
    def export_data(self, output_dir: str = DEFAULT_EXPORT_DIR, formats: list = None):
        """Export database data to various formats"""
        if formats is None:
            formats = ['json']
        
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        logger.info(f"Exporting data to {output_path} in formats: {formats}")
        
        with self.db_manager.get_session() as session:
            # Get statistics
            stats = self.db_manager.get_database_stats(session)
            logger.info(f"Database statistics: {stats}")
            
            # TODO: Implement actual export functionality
            # This would export compounds, targets, pathways, and interactions
            # to JSON, CSV, or other formats as requested
            
            logger.info("Export completed")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive database and import statistics"""
        with self.db_manager.get_session() as session:
            db_stats = self.db_manager.get_database_stats(session)
            
            return {
                'database_stats': db_stats,
                'import_stats': self.stats.copy(),
                'database_url': DATABASE_URL,
                'last_updated': datetime.now().isoformat()
            }


@click.command()
@click.option('--from-chembl', is_flag=True, help='Import compounds from ChEMBL')
@click.option('--from-reactome', is_flag=True, help='Import pathways from Reactome')
@click.option('--compound', help='Import specific compound by ChEMBL ID')
@click.option('--limit', type=int, help='Limit number of compounds to import')
@click.option('--slow', is_flag=True, help='Enable slow mode for API rate limiting')
@click.option('--init-db', is_flag=True, help='Initialize database tables')
@click.option('--export', help='Export data to directory')
@click.option('--stats', is_flag=True, help='Show database statistics')
@click.option('--log-level', default='INFO', help='Set logging level')
def main(from_chembl, from_reactome, compound, limit, slow, init_db, export, stats, log_level):
    """ChEMBL and Reactome Cross-Importer CLI"""
    
    # Set up logging
    logging.getLogger().setLevel(getattr(logging, log_level.upper()))
    
    # Update slow mode setting
    if slow:
        import chembio_importer.config as config
        config.SLOW_MODE = True
        logger.info("Slow mode enabled")
    
    # Initialize importer
    importer = ChemBioImporter()
    
    try:
        # Initialize database if requested
        if init_db:
            importer.initialize_database()
            return
        
        # Show statistics if requested
        if stats:
            statistics = importer.get_statistics()
            click.echo(f"Database Statistics:")
            for key, value in statistics['database_stats'].items():
                click.echo(f"  {key}: {value}")
            return
        
        # Import operations
        if from_chembl or compound:
            importer.import_from_chembl(limit=limit, specific_compound=compound)
        
        if from_reactome:
            importer.import_pathways_from_reactome(targets_only=True)
        
        # Export if requested
        if export:
            importer.export_data(output_dir=export)
        
        # Show final statistics
        final_stats = importer.get_statistics()
        click.echo("\nImport completed successfully!")
        click.echo(f"Final statistics: {final_stats['import_stats']}")
        
    except Exception as e:
        logger.error(f"Import failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
