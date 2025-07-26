"""
Database operations and connection management
"""
import logging
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from .config import DATABASE_URL, DATABASE_ECHO
from .models import Base, Compound, Target, Pathway, CompoundTargetInteraction, Synonym, ImportLog

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and operations"""
    
    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url
        self.engine = create_engine(database_url, echo=DATABASE_ECHO)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
    def create_tables(self):
        """Create all tables if they don't exist"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except SQLAlchemyError as e:
            logger.error(f"Error creating database tables: {e}")
            raise
    
    def drop_tables(self):
        """Drop all tables (use with caution)"""
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.info("Database tables dropped successfully")
        except SQLAlchemyError as e:
            logger.error(f"Error dropping database tables: {e}")
            raise
    
    @contextmanager
    def get_session(self):
        """Context manager for database sessions"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()
    
    def get_or_create_compound(self, session: Session, chembl_id: str, **kwargs) -> tuple[Compound, bool]:
        """Get existing compound or create new one"""
        compound = session.query(Compound).filter(Compound.chembl_id == chembl_id).first()
        created = False
        
        if not compound:
            compound = Compound(chembl_id=chembl_id, **kwargs)
            session.add(compound)
            created = True
            logger.debug(f"Created new compound: {chembl_id}")
        else:
            # Update existing compound with new data
            for key, value in kwargs.items():
                if hasattr(compound, key) and value is not None:
                    setattr(compound, key, value)
            logger.debug(f"Updated existing compound: {chembl_id}")
        
        return compound, created
    
    def get_or_create_target(self, session: Session, chembl_id: str, **kwargs) -> tuple[Target, bool]:
        """Get existing target or create new one"""
        target = session.query(Target).filter(Target.chembl_id == chembl_id).first()
        created = False
        
        if not target:
            target = Target(chembl_id=chembl_id, **kwargs)
            session.add(target)
            created = True
            logger.debug(f"Created new target: {chembl_id}")
        else:
            # Update existing target with new data
            for key, value in kwargs.items():
                if hasattr(target, key) and value is not None:
                    setattr(target, key, value)
            logger.debug(f"Updated existing target: {chembl_id}")
        
        return target, created
    
    def get_or_create_pathway(self, session: Session, stable_id: str, **kwargs) -> tuple[Pathway, bool]:
        """Get existing pathway or create new one"""
        pathway = session.query(Pathway).filter(Pathway.stable_id == stable_id).first()
        created = False
        
        if not pathway:
            pathway = Pathway(stable_id=stable_id, **kwargs)
            session.add(pathway)
            created = True
            logger.debug(f"Created new pathway: {stable_id}")
        else:
            # Update existing pathway with new data
            for key, value in kwargs.items():
                if hasattr(pathway, key) and value is not None:
                    setattr(pathway, key, value)
            logger.debug(f"Updated existing pathway: {stable_id}")
        
        return pathway, created
    
    def get_or_create_synonym(self, session: Session, name: str, synonym_type: str = None, 
                             source: str = None) -> tuple[Synonym, bool]:
        """Get existing synonym or create new one"""
        query = session.query(Synonym).filter(Synonym.name == name)
        if synonym_type:
            query = query.filter(Synonym.synonym_type == synonym_type)
        if source:
            query = query.filter(Synonym.source == source)
        
        synonym = query.first()
        created = False
        
        if not synonym:
            synonym = Synonym(name=name, synonym_type=synonym_type, source=source)
            session.add(synonym)
            created = True
            logger.debug(f"Created new synonym: {name}")
        
        return synonym, created
    
    def create_compound_target_interaction(self, session: Session, compound: Compound, 
                                         target: Target, **kwargs) -> CompoundTargetInteraction:
        """Create a new compound-target interaction"""
        # Check if interaction already exists
        existing = session.query(CompoundTargetInteraction).filter(
            CompoundTargetInteraction.compound_id == compound.id,
            CompoundTargetInteraction.target_id == target.id,
            CompoundTargetInteraction.mechanism == kwargs.get('mechanism'),
            CompoundTargetInteraction.activity_type == kwargs.get('activity_type')
        ).first()
        
        if existing:
            # Update existing interaction
            for key, value in kwargs.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            logger.debug(f"Updated interaction: {compound.chembl_id} -> {target.chembl_id}")
            return existing
        else:
            # Create new interaction
            interaction = CompoundTargetInteraction(
                compound_id=compound.id,
                target_id=target.id,
                **kwargs
            )
            session.add(interaction)
            logger.debug(f"Created interaction: {compound.chembl_id} -> {target.chembl_id}")
            return interaction
    
    def bulk_insert_compounds(self, session: Session, compounds_data: List[Dict[str, Any]]) -> int:
        """Bulk insert compounds for better performance"""
        try:
            # Use bulk_insert_mappings for better performance
            session.bulk_insert_mappings(Compound, compounds_data)
            return len(compounds_data)
        except IntegrityError as e:
            session.rollback()
            logger.warning(f"Bulk insert failed, falling back to individual inserts: {e}")
            # Fall back to individual inserts to handle duplicates
            count = 0
            for compound_data in compounds_data:
                try:
                    compound, created = self.get_or_create_compound(session, **compound_data)
                    if created:
                        count += 1
                except Exception as e:
                    logger.error(f"Error inserting compound {compound_data.get('chembl_id')}: {e}")
            return count
    
    def get_compound_count(self, session: Session) -> int:
        """Get total number of compounds in database"""
        return session.query(Compound).count()
    
    def get_target_count(self, session: Session) -> int:
        """Get total number of targets in database"""
        return session.query(Target).count()
    
    def get_pathway_count(self, session: Session) -> int:
        """Get total number of pathways in database"""
        return session.query(Pathway).count()
    
    def get_interaction_count(self, session: Session) -> int:
        """Get total number of compound-target interactions in database"""
        return session.query(CompoundTargetInteraction).count()
    
    def log_import_operation(self, session: Session, operation_type: str, status: str,
                           **kwargs) -> ImportLog:
        """Log an import operation"""
        import_log = ImportLog(
            operation_type=operation_type,
            status=status,
            **kwargs
        )
        session.add(import_log)
        return import_log
    
    def get_database_stats(self, session: Session) -> Dict[str, int]:
        """Get comprehensive database statistics"""
        return {
            'compounds': self.get_compound_count(session),
            'targets': self.get_target_count(session),
            'pathways': self.get_pathway_count(session),
            'interactions': self.get_interaction_count(session),
            'synonyms': session.query(Synonym).count(),
        }
    
    def vacuum_database(self):
        """Optimize database (SQLite specific)"""
        if 'sqlite' in self.database_url.lower():
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("VACUUM"))
                logger.info("Database vacuumed successfully")
            except SQLAlchemyError as e:
                logger.error(f"Error vacuuming database: {e}")


# Global database manager instance
db_manager = DatabaseManager()
