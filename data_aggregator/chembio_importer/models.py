"""
Database models for ChEMBL and Reactome data using SQLAlchemy ORM
"""
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, JSON,
    ForeignKey, Table, Index, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()

# Association tables for many-to-many relationships
compound_synonyms = Table(
    'compound_synonyms',
    Base.metadata,
    Column('compound_id', Integer, ForeignKey('compounds.id'), primary_key=True),
    Column('synonym_id', Integer, ForeignKey('synonyms.id'), primary_key=True)
)

target_pathways = Table(
    'target_pathways',
    Base.metadata,
    Column('target_id', Integer, ForeignKey('targets.id'), primary_key=True),
    Column('pathway_id', Integer, ForeignKey('pathways.id'), primary_key=True)
)

compound_pathways = Table(
    'compound_pathways',
    Base.metadata,
    Column('compound_id', Integer, ForeignKey('compounds.id'), primary_key=True),
    Column('pathway_id', Integer, ForeignKey('pathways.id'), primary_key=True)
)


class Compound(Base):
    """ChEMBL compound with comprehensive metadata"""
    __tablename__ = 'compounds'
    
    id = Column(Integer, primary_key=True)
    chembl_id = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=True)
    canonical_smiles = Column(Text, nullable=True)
    inchi = Column(Text, nullable=True)
    inchi_key = Column(String(27), nullable=True, index=True)
    
    # Molecular properties
    molecular_weight = Column(Float, nullable=True)
    logp = Column(Float, nullable=True)
    alogp = Column(Float, nullable=True)
    tpsa = Column(Float, nullable=True)  # Topological Polar Surface Area
    hbd = Column(Integer, nullable=True)  # Hydrogen bond donors
    hba = Column(Integer, nullable=True)  # Hydrogen bond acceptors
    rotatable_bonds = Column(Integer, nullable=True)
    aromatic_rings = Column(Integer, nullable=True)  # Number of aromatic rings
    aliphatic_rings = Column(Integer, nullable=True)  # Number of aliphatic rings
    
    # Classification
    compound_type = Column(String(100), nullable=True)  # small_molecule, biologic, etc
    approval_status = Column(String(50), nullable=True)
    max_phase = Column(Integer, nullable=True)  # Clinical trial phase
    first_approval = Column(Integer, nullable=True)  # Year of first approval
    
    # Effect profile (JSON field for flexible storage)
    effect_profile = Column(JSON, nullable=True)
    
    # Additional metadata
    additional_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    synonyms = relationship("Synonym", secondary=compound_synonyms, back_populates="compounds")
    target_interactions = relationship("CompoundTargetInteraction", back_populates="compound")
    pathways = relationship("Pathway", secondary=compound_pathways, back_populates="compounds")
    
    def __repr__(self):
        return f"<Compound(chembl_id='{self.chembl_id}', name='{self.name}')>"


class Target(Base):
    """Biological targets (proteins, enzymes, receptors)"""
    __tablename__ = 'targets'
    
    id = Column(Integer, primary_key=True)
    chembl_id = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=True)
    gene_symbol = Column(String(50), nullable=True, index=True)
    organism = Column(String(200), nullable=True)
    target_type = Column(String(100), nullable=True)  # enzyme, receptor, transporter, etc
    
    # External identifiers
    uniprot_id = Column(String(20), nullable=True, index=True)
    ensembl_id = Column(String(50), nullable=True)
    
    # Target details
    description = Column(Text, nullable=True)
    protein_class = Column(String(200), nullable=True)
    
    # Additional metadata
    additional_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    compound_interactions = relationship("CompoundTargetInteraction", back_populates="target")
    pathways = relationship("Pathway", secondary=target_pathways, back_populates="targets")
    
    def __repr__(self):
        return f"<Target(chembl_id='{self.chembl_id}', gene_symbol='{self.gene_symbol}')>"


class CompoundTargetInteraction(Base):
    """Compound-target interactions with mechanism and affinity data"""
    __tablename__ = 'compound_target_interactions'
    
    id = Column(Integer, primary_key=True)
    compound_id = Column(Integer, ForeignKey('compounds.id'), nullable=False)
    target_id = Column(Integer, ForeignKey('targets.id'), nullable=False)
    
    # Interaction details
    mechanism = Column(String(200), nullable=True)  # agonist, antagonist, inhibitor, etc
    activity_type = Column(String(50), nullable=True)  # IC50, Ki, EC50, Kd, etc
    activity_value = Column(Float, nullable=True)  # Numeric value
    activity_units = Column(String(20), nullable=True)  # nM, μM, etc
    activity_relation = Column(String(10), nullable=True)  # =, <, >, etc
    
    # Quality and source
    confidence_score = Column(Float, nullable=True)
    data_validity_comment = Column(String(200), nullable=True)
    assay_chembl_id = Column(String(20), nullable=True)
    document_chembl_id = Column(String(20), nullable=True)
    
    # Additional metadata
    source = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    additional_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    compound = relationship("Compound", back_populates="target_interactions")
    target = relationship("Target", back_populates="compound_interactions")
    
    # Constraints
    __table_args__ = (
        Index('idx_compound_target', 'compound_id', 'target_id'),
        UniqueConstraint('compound_id', 'target_id', 'mechanism', 'activity_type', 
                        name='uq_compound_target_mechanism'),
    )
    
    def __repr__(self):
        return f"<CompoundTargetInteraction(compound='{self.compound.chembl_id}', target='{self.target.chembl_id}', mechanism='{self.mechanism}')>"


class Pathway(Base):
    """Reactome biological pathways"""
    __tablename__ = 'pathways'
    
    id = Column(Integer, primary_key=True)
    stable_id = Column(String(50), unique=True, nullable=False, index=True)  # R-HSA-198978
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    species = Column(String(100), nullable=True)
    
    # Hierarchy
    parent_pathway_id = Column(Integer, ForeignKey('pathways.id'), nullable=True)
    pathway_level = Column(Integer, nullable=True)  # 0=top level, 1=sublevel, etc
    
    # External links
    reactome_url = Column(String(200), nullable=True)
    
    # Additional metadata
    additional_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    targets = relationship("Target", secondary=target_pathways, back_populates="pathways")
    compounds = relationship("Compound", secondary=compound_pathways, back_populates="pathways")
    children = relationship("Pathway", backref="parent", remote_side=[id])
    
    def __repr__(self):
        return f"<Pathway(stable_id='{self.stable_id}', name='{self.name}')>"


class Synonym(Base):
    """Compound synonyms and alternative names"""
    __tablename__ = 'synonyms'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(500), nullable=False, index=True)
    synonym_type = Column(String(50), nullable=True)  # TRADE_NAME, INN, USAN, etc
    source = Column(String(100), nullable=True)  # ChEMBL, PubChem, DrugBank, etc
    
    # Relationships
    compounds = relationship("Compound", secondary=compound_synonyms, back_populates="synonyms")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('name', 'synonym_type', 'source', name='uq_synonym_name_type_source'),
    )
    
    def __repr__(self):
        return f"<Synonym(name='{self.name}', type='{self.synonym_type}')>"


class ImportLog(Base):
    """Log of import operations for tracking and debugging"""
    __tablename__ = 'import_logs'
    
    id = Column(Integer, primary_key=True)
    operation_type = Column(String(50), nullable=False)  # chembl_import, reactome_import, etc
    status = Column(String(20), nullable=False)  # started, completed, failed
    records_processed = Column(Integer, nullable=True)
    records_imported = Column(Integer, nullable=True)
    records_updated = Column(Integer, nullable=True)
    records_failed = Column(Integer, nullable=True)
    
    # Timing
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Details
    parameters = Column(JSON, nullable=True)  # Import parameters used
    error_message = Column(Text, nullable=True)
    summary = Column(JSON, nullable=True)  # Summary statistics
    
    def __repr__(self):
        return f"<ImportLog(operation='{self.operation_type}', status='{self.status}')>"
