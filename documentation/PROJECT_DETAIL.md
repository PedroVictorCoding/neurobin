# Neurobin — Project Detail (Improved)

This document captures the *core ideas* of the current Neurobin codebase (compound database + interactions + research + intake logging) and proposes an improved, cleaner implementation with stronger data provenance, scalability, and maintainability.

Implementation note: MolProp bridge setup is documented in `documentation/MOLPROP_SETUP.md`.

## 1) Product Vision

Neurobin is a neurochemical compound research and personal-tracking platform that:
- Maintains high-quality compound/target/interactions data with explicit evidence and confidence
- Enables community contributions (research snippets, structured change requests, moderation)
- Lets individuals privately log intakes and visualize effect windows and overlaps

## 2) Primary Users & Jobs-To-Be-Done

### Researchers / power users
- Search compounds and targets; understand mechanisms and interactions quickly
- Validate claims by inspecting sources and evidence
- Export data (CSV/JSON) for analysis

### Community contributors / moderators
- Propose changes to compound pages with structured diffs and citations
- Review/vote/approve with audit trails and role-weighted trust

### Personal users
- Log intakes with dosage + time + notes privately
- Visualize timelines (onset → peak → offset) and overlaps across compounds

## 3) Core Domain (Canonical Entities)

### Knowledge base (public/shared)
- **Compound**
  - `name`, `slug`, `aliases[]`, `description`, `smiles`, optional external IDs (e.g. `chembl_id`, `pubchem_cid`)
- **Target**
  - `name`, `type`, optional IDs (`uniprot_id`, `ensembl_id`), `description`
- **Mechanism / Interaction**
  - **CompoundTargetInteraction**: compound ↔ target with `action_type` (agonist/antagonist/etc), optional affinity, and evidence
  - **CompoundCompoundInteraction**: derived relationship between two compounds via shared targets (synergy/competition/etc) with rules + evidence
- **Category / Tag**
  - controlled vocab for categories and free-form tags for discovery
- **Evidence**
  - a first-class object attached to any “claim” (interaction, safety, effect window, etc.)

### Research content (community)
- **ResearchSnippet**
  - `title`, `content`, links to compounds/targets, `snippet_type`, `visibility`, `status`
  - references: `doi`, `pubmed_id`, `source_url`, plus extracted metadata
- **Comment / Vote / Review**
  - structured feedback, vote weight by role/trust

### Personal data (private by default)
- **IntakeLog**
  - compound, dose, unit, timestamp, notes; strictly user-scoped access
- **EffectWindow**
  - onset/peak/duration/half-life estimates (can be global defaults + user overrides)

### Governance
- **ChangeRequest**
  - structured proposals: field-level patches with required citations and reviewer outcomes
- **Role / Trust**
  - roles (guest/user/reviewer/mod/admin) + optional reputation signals (rate limits, vote weight)

## 4) The Key Improvement: Evidence-First Data Model

Instead of storing facts directly on core models without provenance, store them as **claims with evidence**:
- Any interaction, safety score, effect window, or assertion has:
  - `statement` (what is being claimed)
  - `subject` (compound/target/etc)
  - `value` (typed value where applicable)
  - `confidence` (low/medium/high or 1–5)
  - `evidence[]` (citations + extraction metadata)
  - `source_type` (chembl/pubchem/uniprot/pubmed/manual/etc)
  - `created_by` (system importer vs human)

This makes imports reproducible, community edits auditable, and conflicting data resolvable.

## 5) Data Ingestion (Replaces One-Off “Populate Everything” Scripts)

The current `core/populate_all_data.py` demonstrates the right ambition (multiple APIs) but should become a robust ingestion pipeline:
- **Idempotent jobs**: each importer can be re-run safely without duplicating data
- **Checkpointing**: resume from last successful cursor/page (ChEMBL offsets, PubMed queries)
- **Rate limiting + retries** per provider (429 backoff, exponential retry)
- **Provenance**: every imported field produces Evidence records
- **Queue-based execution**: background workers (Celery/RQ) for long-running sync
- **Observability**: job status, counts, error samples, provider latency

Suggested importers:
- ChEMBL: compounds, targets, mechanisms, activities
- PubChem: structure/properties enrichment
- UniProt: target annotations
- PubMed: evidence discovery for snippets (optional)

## 6) API & UI Principles

### API (Versioned)
- `/api/v1/...` for stable clients; `/api/internal/...` for admin ops
- Prefer queryable endpoints over bespoke ones:
  - `/compounds?search=&category=&has_target=`
  - `/targets?search=&type=`
  - `/interactions?compound_id=&target_id=&confidence=`
- Include evidence in responses (or behind `?include=evidence`) to keep payloads manageable

### UI (Progressive)
- Phase 1: server-rendered pages + DRF browsable API (fastest)
- Phase 2: React/Vite SPA for richer discovery + graphs + timelines

## 7) Architecture (Improved, Still Practical)

### Baseline (recommended)
- **Django + DRF** for API, admin, auth
- **PostgreSQL** as the default DB (SQLite only for dev)
- **Redis + Celery** for imports and heavy computations (interaction derivation)
- **S3-compatible object storage** for uploads (profile images, assets)

### Service boundaries (inside the monolith)
- `domain/` (pure business logic, no Django imports)
- `services/` (use-cases: import, derive interactions, search indexing)
- `adapters/` (external APIs: ChEMBL/PubChem/UniProt/PubMed clients)
- `api/` (serializers/viewsets/routers)

### Performance & correctness
- Derived interactions computed asynchronously, cached, and invalidated by changes
- Strong constraints: unique keys on external IDs, normalized target identifiers
- Deterministic slugs and canonical name normalization

## 8) Security, Privacy, and Safety

- Secrets via environment variables; no committed `SECRET_KEY`
- Token auth with sensible lifetimes; refresh rotation; rate limiting
- Personal logs are private by default (strict object-level permission checks)
- Moderation actions and change approvals are audited
- Safety disclaimer and “not medical advice” messaging in the UI

## 9) Quality Bar (What “Improved” Means)

Minimum engineering standards:
- Automated tests for: permissions, core serializers, ingestion idempotency, interaction derivation rules
- Migrations are deterministic and reviewed (no schema drift)
- Static typing for import/services modules where feasible (mypy/pyright)
- CI: lint + unit tests + migrations check

## 10) Delivery Plan (V2 Roadmap)

### Phase 0 — Spec & contracts
- Finalize canonical entities + evidence model
- Freeze v1 endpoints that must remain stable

### Phase 1 — MVP
- Auth + roles
- Compounds/targets CRUD + search
- Evidence-backed compound-target interactions

### Phase 2 — Imports & derivations
- ChEMBL import pipeline + job dashboard
- Derived compound-compound interactions

### Phase 3 — Personal tracking
- Intake logs + effect window visualization + overlap analysis

### Phase 4 — Community workflows
- Research snippets + citations + review/voting
- Change requests + approval + audit

## 11) Explicit Non-Goals (For Scope Control)

- Medical dosing recommendations
- Real-time clinical decision support
- Fully automated “truth” scoring without human review

## 12) Open Questions

1) Should v2 preserve all existing v1 data/users, or is re-import acceptable?
2) What is the priority order: compounds → imports → intake logs → community editing?
3) Is the UI primarily admin-centric, public discovery-centric, or personal tracking-centric?
