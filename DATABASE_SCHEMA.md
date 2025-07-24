# Neurobin Database Schema Documentation

## Overview

Neurobin uses SQLite for development with a comprehensive relational database schema supporting compound management, research documentation, user tracking, and interaction modeling.

## Core Apps & Models

### 1. Compounds App

#### CompoundCategories
Categorization system for grouping compounds by type/class.

```sql
CREATE TABLE compounds_compoundcategories (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    description TEXT
);
```

**Purpose:** Group compounds (e.g., "Nootropics", "Psychedelics", "Stimulants")

#### Target
Molecular targets that compounds can interact with.

```sql
CREATE TABLE compounds_target (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    type VARCHAR(50),  -- receptor, enzyme, transporter, etc.
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Target Types:**
- `receptor` - Neurotransmitter receptors
- `enzyme` - Metabolic enzymes
- `transporter` - Membrane transporters
- `ion_channel` - Ion channels
- `protein` - Other proteins
- `other` - Miscellaneous targets

#### CompoundMechanismOfAction
Defines how compounds interact with molecular targets.

```sql
CREATE TABLE compounds_compoundmechanismofaction (
    id INTEGER PRIMARY KEY,
    target_name VARCHAR(200) NOT NULL,
    target_type VARCHAR(50),
    target_interaction VARCHAR(100),
    description TEXT
);
```

**Interaction Types:**
- `agonist` - Full agonist
- `antagonist` - Competitive antagonist
- `partial_agonist` - Partial agonist
- `inverse_agonist` - Inverse agonist
- `pam` - Positive allosteric modulator
- `nam` - Negative allosteric modulator
- `inhibitor` - Enzyme inhibitor
- `activator` - Enzyme activator
- `upregulator` - Expression upregulator
- `downregulator` - Expression downregulator

#### Compound
Core compound model containing all compound information.

```sql
CREATE TABLE compounds_compound (
    id INTEGER PRIMARY KEY,
    name VARCHAR(500) UNIQUE NOT NULL,
    description TEXT,
    slug VARCHAR(50) UNIQUE,
    aliases VARCHAR(255),  -- Comma-separated alternative names
    smiles VARCHAR(1000),  -- SMILES notation
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Many-to-many relationships
CREATE TABLE compounds_compound_categories (
    compound_id INTEGER REFERENCES compounds_compound(id),
    compoundcategories_id INTEGER REFERENCES compounds_compoundcategories(id),
    PRIMARY KEY (compound_id, compoundcategories_id)
);

CREATE TABLE compounds_compound_mechanism_of_action (
    compound_id INTEGER REFERENCES compounds_compound(id),
    compoundmechanismofaction_id INTEGER REFERENCES compounds_compoundmechanismofaction(id),
    PRIMARY KEY (compound_id, compoundmechanismofaction_id)
);
```

#### CompoundRating
User rating system for compounds (1-5 stars).

```sql
CREATE TABLE compounds_compoundrating (
    id INTEGER PRIMARY KEY,
    compound_id INTEGER REFERENCES compounds_compound(id),
    user_id INTEGER REFERENCES auth_user(id),
    score INTEGER CHECK (score >= 1 AND score <= 5),
    comment TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(compound_id, user_id)
);
```

#### CompoundSafetyScreening
Safety assessment data for compounds.

```sql
CREATE TABLE compounds_compoundsafetyscreening (
    id INTEGER PRIMARY KEY,
    compound_id INTEGER REFERENCES compounds_compound(id),
    liver_toxicity INTEGER CHECK (liver_toxicity >= 1 AND liver_toxicity <= 5),
    kidney_toxicity INTEGER CHECK (kidney_toxicity >= 1 AND kidney_toxicity <= 5),
    cardiovascular_risk INTEGER CHECK (cardiovascular_risk >= 1 AND cardiovascular_risk <= 5),
    confidence_level INTEGER CHECK (confidence_level >= 1 AND confidence_level <= 5),
    created_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### EffectWindow
Pharmacokinetic modeling for compound effects over time.

```sql
CREATE TABLE compounds_effectwindow (
    id INTEGER PRIMARY KEY,
    compound_id INTEGER REFERENCES compounds_compound(id),
    effect_shape VARCHAR(20) DEFAULT 'ramp',  -- ramp, flat-top, custom
    onset_minutes INTEGER NOT NULL,
    peak_min_minutes INTEGER,
    peak_max_minutes INTEGER,
    duration_minutes INTEGER NOT NULL,
    half_life_minutes INTEGER,
    notes TEXT,
    created_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### CompoundTargetInteraction
Defines how individual compounds interact with specific targets.

```sql
CREATE TABLE compounds_compoundtargetinteraction (
    id INTEGER PRIMARY KEY,
    compound_id INTEGER REFERENCES compounds_compound(id),
    target_id INTEGER REFERENCES compounds_target(id),
    interaction_type VARCHAR(50) NOT NULL,
    mechanism VARCHAR(200),
    affinity_value REAL,
    affinity_unit VARCHAR(10),
    confidence VARCHAR(10) DEFAULT 'medium',  -- low, medium, high
    source VARCHAR(500),
    created_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### CompoundToCompoundTargetInteraction
Models interactions between compounds via shared targets.

```sql
CREATE TABLE compounds_compoundtocompoundtargetinteraction (
    id INTEGER PRIMARY KEY,
    compound_a_id INTEGER REFERENCES compounds_compound(id),
    compound_b_id INTEGER REFERENCES compounds_compound(id),
    target_id INTEGER REFERENCES compounds_target(id),
    interaction_type VARCHAR(50) NOT NULL,
    description TEXT,
    confidence VARCHAR(10) DEFAULT 'medium',
    source VARCHAR(500),
    created_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Interaction Types:**
- `synergistic` - Enhanced effects
- `antagonistic` - Opposing effects
- `competitive` - Competition for same binding site
- `additive` - Combined effects
- `potentiating` - One enhances the other
- `inhibitory` - One inhibits the other

### 2. Research App

#### ResearchSnippet
Community-contributed research content about compounds.

```sql
CREATE TABLE research_researchsnippet (
    id INTEGER PRIMARY KEY,
    title VARCHAR(300) NOT NULL,
    content TEXT NOT NULL,
    compound_id INTEGER REFERENCES compounds_compound(id),
    snippet_type VARCHAR(50) DEFAULT 'general',
    visibility VARCHAR(20) DEFAULT 'public',
    status VARCHAR(20) DEFAULT 'draft',
    source_title VARCHAR(500),
    source_url VARCHAR(500),
    doi VARCHAR(100),
    pubmed_id VARCHAR(20),
    confidence_score INTEGER CHECK (confidence_score >= 1 AND confidence_score <= 5),
    ai_generated BOOLEAN DEFAULT FALSE,
    ai_summary TEXT,
    view_count INTEGER DEFAULT 0,
    created_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Snippet Types:**
- `general` - General research
- `mechanism` - Mechanism of action
- `pharmacology` - Pharmacological data
- `safety` - Safety information
- `clinical` - Clinical studies
- `dosage` - Dosage information
- `interaction` - Drug interactions
- `experience` - User experiences

**Status Types:**
- `draft` - Work in progress
- `submitted` - Awaiting review
- `validated` - Community validated
- `flagged` - Flagged for review
- `rejected` - Rejected by community

#### SnippetReview
Community voting system for research quality.

```sql
CREATE TABLE research_snippetreview (
    id INTEGER PRIMARY KEY,
    snippet_id INTEGER REFERENCES research_researchsnippet(id),
    reviewer_id INTEGER REFERENCES auth_user(id),
    vote_type VARCHAR(20) NOT NULL,  -- validate, reject
    comment TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snippet_id, reviewer_id)
);
```

#### SnippetTag
Tagging system for categorizing research content.

```sql
CREATE TABLE research_snippettag (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#007bff',  -- Hex color
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_snippettagging (
    id INTEGER PRIMARY KEY,
    snippet_id INTEGER REFERENCES research_researchsnippet(id),
    tag_id INTEGER REFERENCES research_snippettag(id),
    tagged_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snippet_id, tag_id)
);
```

#### UserRole
Extended user roles for research system permissions.

```sql
CREATE TABLE research_userrole (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES auth_user(id) UNIQUE,
    role VARCHAR(20) DEFAULT 'authenticated',
    vote_weight REAL DEFAULT 1.0,
    can_moderate BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Role Types:**
- `guest` - Unauthenticated users
- `authenticated` - Basic registered users
- `trusted_reviewer` - Users with proven track record
- `moderator` - Content moderators
- `admin` - System administrators

#### ResearchSettings
Global configuration for research system.

```sql
CREATE TABLE research_researchsettings (
    id INTEGER PRIMARY KEY,
    validation_threshold INTEGER DEFAULT 3,
    flagging_threshold INTEGER DEFAULT 2,
    high_confidence_threshold INTEGER DEFAULT 5,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3. Logs App

#### IntakeLog
Personal compound intake tracking for users.

```sql
CREATE TABLE logs_intakelog (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES auth_user(id),
    compound_id INTEGER REFERENCES compounds_compound(id),
    amount VARCHAR(100),
    unit VARCHAR(16) DEFAULT 'mg',
    taken_at DATETIME NOT NULL,
    notes TEXT
);
```

**Unit Types:**
- `mg` - Milligrams
- `g` - Grams
- `mcg` - Micrograms
- `ml` - Milliliters
- `drops` - Drops
- `units` - Units
- `other` - Other

### 4. Accounts App

#### UserProfile
Extended user profile information.

```sql
CREATE TABLE accounts_userprofile (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES auth_user(id) UNIQUE,
    profile_image VARCHAR(100),
    bio TEXT,
    location VARCHAR(100),
    website VARCHAR(200),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5. Change Requests App

#### ChangeRequest
Collaborative editing system for compound data.

```sql
CREATE TABLE change_requests_changerequest (
    id INTEGER PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    content_type_id INTEGER REFERENCES django_content_type(id),
    object_id INTEGER,
    changes TEXT,  -- JSON field
    status VARCHAR(20) DEFAULT 'pending',
    submitted_by_id INTEGER REFERENCES auth_user(id),
    reviewed_by_id INTEGER REFERENCES auth_user(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Status Types:**
- `pending` - Awaiting review
- `approved` - Approved and applied
- `rejected` - Rejected
- `draft` - Work in progress

## Data Relationships

### Key Relationships

1. **Compound ↔ Mechanisms** (Many-to-Many)
   - Compounds can have multiple mechanisms of action
   - Mechanisms can be shared across compounds

2. **Compound ↔ Categories** (Many-to-Many)
   - Compounds can belong to multiple categories
   - Categories contain multiple compounds

3. **Compound ↔ Interactions** (Self-referencing Many-to-Many)
   - Compounds interact with other compounds via shared targets
   - Bidirectional relationship tracking

4. **User ↔ Research** (One-to-Many)
   - Users create research snippets
   - Users review other users' research

5. **User ↔ Logs** (One-to-Many)
   - Users maintain personal intake logs
   - Privacy-focused design

## Indexes and Performance

### Key Indexes
```sql
-- Compound searches
CREATE INDEX idx_compound_name ON compounds_compound(name);
CREATE INDEX idx_compound_slug ON compounds_compound(slug);

-- Research snippets
CREATE INDEX idx_snippet_compound ON research_researchsnippet(compound_id);
CREATE INDEX idx_snippet_status ON research_researchsnippet(status);
CREATE INDEX idx_snippet_created ON research_researchsnippet(created_at);

-- User logs
CREATE INDEX idx_log_user_date ON logs_intakelog(user_id, taken_at);

-- Interactions
CREATE INDEX idx_interaction_compounds ON compounds_compoundtocompoundtargetinteraction(compound_a_id, compound_b_id);
```

## Data Integrity

### Constraints
- Unique compound names and slugs
- Rating scores constrained to 1-5 range
- Safety screening scores constrained to 1-5 range
- One rating per user per compound
- One review per user per snippet

### Cascading Deletes
- User deletion cascades to logs and research
- Compound deletion cascades to related data
- Target deletion handled gracefully

## Migration History

The schema has evolved through 25+ Django migrations, key milestones:
- Initial compound and category models
- Research snippet system addition
- Interaction modeling implementation
- Safety screening integration
- Effect window pharmacokinetics
- Change request system

## Backup and Maintenance

### Recommended Practices
- Regular SQLite database backups
- Index maintenance for performance
- Constraint validation checks
- Data archival for old logs
- Research content moderation

---

**Schema Version:** 1.0  
**Last Updated:** July 2025  
**Database Engine:** SQLite (development), PostgreSQL (production ready)
