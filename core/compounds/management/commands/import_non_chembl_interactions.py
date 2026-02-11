from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from collections.abc import Iterable, Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection

from compounds.interaction_engine import (
    build_evidence_uid,
    build_interaction_context_key,
    canonicalize_mechanism,
    compute_evidence_weight,
    get_context_review_rows,
    rebuild_compound_pair_interactions,
    rebuild_context_consensus,
)
from compounds.models import Compound, CompoundTargetInteractionEvidence, Target, normalize_target_name
from compounds.models import normalize_compound_lookup_key, normalize_compound_name

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)


_SOURCE_FILE_OPTIONS = {
    "iuphar": "iuphar_file",
    "bindingdb": "bindingdb_file",
    "drugbank": "drugbank_file",
    "dgidb": "dgidb_file",
    "pharmgkb": "pharmgkb_file",
}

_SOURCE_LABELS = {
    "iuphar": "IUPHAR",
    "bindingdb": "BindingDB",
    "drugbank": "DrugBank",
    "dgidb": "DGIdb",
    "pharmgkb": "PharmGKB",
}

_SOURCE_DEFAULT_EVIDENCE = {
    "iuphar": "high",
    "bindingdb": "medium",
    "drugbank": "high",
    "dgidb": "medium",
    "pharmgkb": "medium",
}

_FIELD_ALIASES = {
    "source_record_id": ["source_record_id", "interaction_id", "record_id", "id"],
    "source_url": ["source_url", "url", "link", "reference_url"],
    "compound_chembl_id": ["compound_chembl_id", "molecule_chembl_id", "chembl_id", "compound_id"],
    "compound_name": ["compound_name", "drug_name", "ligand_name", "molecule_name", "chemical_name", "compound"],
    "compound_smiles": [
        "compound_smiles",
        "ligand_smiles",
        "smiles",
        "canonical_smiles",
        "isomeric_smiles",
    ],
    "target_chembl_id": ["target_chembl_id", "target_id"],
    "target_name": ["target_name", "target_pref_name", "gene_name", "gene_symbol", "target"],
    "target_gene_name": ["target_gene_name", "gene_name", "target_gene_symbol", "gene_symbol"],
    "action_type": ["action_type", "interaction_type", "interaction_types", "action"],
    "mechanism_of_action": ["mechanism_of_action", "mechanism", "moa", "effect"],
    "evidence_level": ["evidence_level", "evidence", "confidence", "strength"],
    "species": ["species", "organism"],
    "tissue_or_cell_line": ["tissue_or_cell_line", "tissue", "cell_line", "cell_type", "cell"],
    "assay_type": ["assay_type", "assay", "assay_format", "experiment_type"],
    "dose_concentration": ["dose_concentration", "dose", "concentration", "value", "potency"],
    "exposure_time": ["exposure_time", "duration", "time", "incubation_time"],
    "route": ["route", "route_of_administration", "administration_route"],
    "notes": ["notes", "comment", "description", "evidence_statement", "summary"],
    "affinity_type": ["affinity_type", "activity_type", "potency_type", "standard_type"],
    "affinity_relation": ["affinity_relation", "relation", "operator", "original_affinity_relation"],
    "affinity_raw_value": ["affinity_raw_value", "affinity_value", "standard_value", "activity_value", "potency"],
    "affinity_units": ["affinity_units", "standard_units", "units", "unit"],
}

_PARSED_FIELDS = [
    "source_record_id",
    "source_url",
    "compound_chembl_id",
    "compound_name",
    "compound_smiles",
    "target_chembl_id",
    "target_name",
    "target_gene_name",
    "action_type",
    "mechanism_of_action",
    "evidence_level",
    "species",
    "tissue_or_cell_line",
    "assay_type",
    "dose_concentration",
    "exposure_time",
    "route",
    "notes",
    "affinity_type",
    "affinity_relation",
    "affinity_raw_value",
    "affinity_units",
]


class Command(BaseCommand):
    help = (
        "Import non-ChEMBL interaction evidence (IUPHAR, BindingDB, DrugBank, DGIdb, PharmGKB), "
        "compute context-aware weighted consensus, and optionally sync CTIs/pair interactions."
    )

    def __init__(self):
        super().__init__()
        self._compound_index_loaded = False
        self._compound_by_key: dict[str, list[int]] = {}
        self._compound_by_alias_key: dict[str, list[int]] = {}
        self._compound_by_smiles_key: dict[str, list[int]] = {}
        self._compound_by_chembl_id: dict[str, int] = {}
        self._compound_by_name_lc: dict[str, list[int]] = {}
        self._compound_canonical_name: dict[int, str] = {}
        self._compound_tokens: dict[int, set[str]] = {}
        self._compound_smiles_key_by_id: dict[int, str] = {}
        self._compound_name_prefix_ids: dict[str, list[int]] = {}
        self._compound_smiles_prefix_ids: dict[str, list[int]] = {}
        self._compound_obj_cache: dict[int, Compound] = {}
        self._compound_match_cache: dict[str, tuple[str, int | None]] = {}
        self._compound_smiles_match_cache: dict[str, tuple[str, int | None]] = {}
        self._compound_resolve_cache: dict[tuple[str, str, str, bool], tuple[str, int | None]] = {}

        self._target_index_loaded = False
        self._target_by_key: dict[str, list[int]] = {}
        self._target_by_gene_key: dict[str, list[int]] = {}
        self._target_by_chembl_id: dict[str, int] = {}
        self._target_by_name_lc: dict[str, list[int]] = {}
        self._target_canonical_name: dict[int, str] = {}
        self._target_tokens: dict[int, set[str]] = {}
        self._target_name_prefix_ids: dict[str, list[int]] = {}
        self._target_obj_cache: dict[int, Target] = {}
        self._target_match_cache: dict[str, tuple[str, int | None]] = {}
        self._target_resolve_cache: dict[tuple[str, str, str, str, bool], tuple[str, int | None]] = {}
        self._disable_fuzzy_matching = False
        self._model_field_maxlen_cache: dict[tuple[type, str], int | None] = {}

    def add_arguments(self, parser):
        parser.add_argument("--iuphar-file", type=str, help="Path to IUPHAR JSON/CSV/TSV interaction dump.")
        parser.add_argument("--bindingdb-file", type=str, help="Path to BindingDB CSV/TSV interaction dump.")
        parser.add_argument("--drugbank-file", type=str, help="Path to DrugBank CSV/TSV/JSON export.")
        parser.add_argument("--dgidb-file", type=str, help="Path to DGIdb CSV/TSV/JSON export.")
        parser.add_argument("--pharmgkb-file", type=str, help="Path to PharmGKB CSV/TSV/JSON export.")
        parser.add_argument(
            "--allow-drugbank",
            action="store_true",
            help="Confirm DrugBank license usage for this run (or set DRUGBANK_LICENSE_ACCEPTED=true).",
        )
        parser.add_argument(
            "--create-missing-compounds",
            action="store_true",
            help="Create compounds when only name/chembl_id is available and no match exists.",
        )
        parser.add_argument(
            "--create-missing-targets",
            action="store_true",
            help="Create targets when only name/chembl_id is available and no match exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and evaluate rows but do not write evidence/consensus.",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=500,
            help="Emit progress every N parsed rows (default: 500).",
        )
        parser.add_argument(
            "--review-limit",
            type=int,
            default=50,
            help="Maximum low-confidence/conflict contexts to print for curation review.",
        )
        parser.add_argument(
            "--rebuild-pairs",
            action="store_true",
            help="Rebuild compound-compound interactions after syncing CTIs from consensus.",
        )
        parser.add_argument(
            "--show-current",
            action="store_true",
            help="Print the current compound -> target being processed for each parsed row.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Rows per dedupe batch when checking already-imported row fingerprints (default: 2000).",
        )
        parser.add_argument(
            "--skip-existing",
            dest="skip_existing",
            action="store_true",
            help="Skip rows already imported in prior runs using a stable row fingerprint (default: enabled).",
        )
        parser.add_argument(
            "--no-skip-existing",
            dest="skip_existing",
            action="store_false",
            help="Disable pre-check skip of already-imported rows.",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume from per-source checkpoint row offsets.",
        )
        parser.add_argument(
            "--checkpoint-file",
            type=str,
            default="data/import_sources/.non_chembl_import_checkpoint.json",
            help="Path to resume checkpoint file (default: data/import_sources/.non_chembl_import_checkpoint.json).",
        )
        parser.add_argument(
            "--disable-fuzzy-matching",
            action="store_true",
            help="Use exact/alias/SMILES matching only (faster; fewer approximate merges).",
        )
        parser.add_argument(
            "--defer-consensus",
            action="store_true",
            help="Import evidence only and skip consensus/CTI/pair recomputation for this run.",
        )
        parser.add_argument(
            "--no-sync-cti",
            dest="sync_cti",
            action="store_false",
            help="Do not sync CompoundTargetInteraction rows from context consensus.",
        )
        parser.set_defaults(sync_cti=True, skip_existing=True)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        progress_every = max(0, options["progress_every"] or 0)
        create_missing_compounds = options["create_missing_compounds"]
        create_missing_targets = options["create_missing_targets"]
        sync_cti = options["sync_cti"]
        show_current = options["show_current"]
        batch_size = max(1, int(options["batch_size"] or 1))
        skip_existing = bool(options["skip_existing"])
        resume_enabled = bool(options["resume"])
        checkpoint_file = Path(options["checkpoint_file"]).expanduser()
        defer_consensus = bool(options["defer_consensus"])
        self._disable_fuzzy_matching = bool(options["disable_fuzzy_matching"])

        source_paths = {
            source: options[field]
            for source, field in _SOURCE_FILE_OPTIONS.items()
            if options.get(field)
        }
        if not source_paths:
            raise CommandError(
                "No source file provided. Use at least one of: --iuphar-file, --bindingdb-file, "
                "--drugbank-file, --dgidb-file, --pharmgkb-file."
            )

        self.stdout.write(f"[i] Non-ChEMBL import sources: {', '.join(sorted(source_paths.keys()))}")
        if dry_run:
            self.stdout.write(self.style.WARNING("[i] Dry-run mode: no DB writes will be performed."))
        self.stdout.write(
            f"[i] Fast-path settings: batch_size={batch_size} skip_existing={skip_existing} "
            f"resume={resume_enabled} disable_fuzzy={self._disable_fuzzy_matching} "
            f"defer_consensus={defer_consensus}"
        )
        self._configure_db_session_for_bulk_import(dry_run=dry_run)

        if source_paths.get("drugbank") and not self._drugbank_allowed(options):
            raise CommandError(
                "DrugBank import blocked. Pass --allow-drugbank or set DRUGBANK_LICENSE_ACCEPTED=true."
            )
        checkpoint_data = self._load_checkpoint_file(checkpoint_file) if resume_enabled or checkpoint_file else {"sources": {}}

        touched_pairs: set[tuple[int, int]] = set()
        stats = {
            "rows_seen": 0,
            "rows_parse_failed": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "rows_skipped": 0,
            "rows_skipped_existing": 0,
            "rows_resumed_skipped": 0,
            "unknown_mechanism_rows": 0,
            "unresolved_compound": 0,
            "unresolved_target": 0,
            "compound_match_exact": 0,
            "compound_match_alias": 0,
            "compound_match_fuzzy": 0,
            "compound_match_smiles": 0,
            "target_match_exact": 0,
            "target_match_fuzzy": 0,
        }
        current_compound_label = "unknown"
        current_target_label = "unknown"

        for source, file_path in source_paths.items():
            source_label = _SOURCE_LABELS[source]
            path = Path(file_path)
            if not path.exists():
                raise CommandError(f"{source_label} file not found: {path}")
            source_signature = self._source_signature(path)
            source_key = f"{source}:{path.resolve()}"
            source_resume_rows = 0
            source_ckpt = checkpoint_data.get("sources", {}).get(source_key, {})
            if (
                resume_enabled
                and source_ckpt
                and source_ckpt.get("signature") == source_signature
            ):
                source_resume_rows = int(source_ckpt.get("rows_completed", 0) or 0)

            self.stdout.write(f"[i] {source_label}: reading rows from {path}")
            if source_resume_rows:
                self.stdout.write(f"[i] {source_label}: resuming from row {source_resume_rows}")
            source_rows = 0
            pending_parsed: list[dict[str, Any]] = []
            for row in self._iter_rows(source, path):
                source_rows += 1
                stats["rows_seen"] += 1
                if source_resume_rows and source_rows <= source_resume_rows:
                    stats["rows_resumed_skipped"] += 1
                    continue
                try:
                    parsed = self._parse_row(source, row)
                except Exception as exc:
                    stats["rows_parse_failed"] += 1
                    if progress_every and source_rows <= 5:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[w] Parse failed for {source_label} row {source_rows}: {exc}"
                            )
                        )
                    continue
                current_compound_label = self._format_current_entity_label(
                    parsed.get("compound_name", ""),
                    parsed.get("compound_chembl_id", ""),
                    parsed.get("compound_smiles", ""),
                )
                current_target_label = self._format_current_entity_label(
                    parsed.get("target_name", ""),
                    parsed.get("target_chembl_id", ""),
                    parsed.get("target_gene_name", ""),
                )
                if show_current:
                    self.stdout.write(
                        f"[r] row={stats['rows_seen']} testing {current_compound_label} -> {current_target_label}",
                        ending="\r",
                    )
                pending_parsed.append(
                    {
                        "parsed": parsed,
                        "row_uid": self._build_source_row_uid(source_label, parsed),
                    }
                )
                if len(pending_parsed) >= batch_size:
                    self._process_parsed_batch(
                        source=source,
                        source_label=source_label,
                        pending_rows=pending_parsed,
                        touched_pairs=touched_pairs,
                        stats=stats,
                        dry_run=dry_run,
                        create_missing_compounds=create_missing_compounds,
                        create_missing_targets=create_missing_targets,
                        skip_existing=skip_existing,
                    )
                    pending_parsed.clear()

                if progress_every and stats["rows_seen"] % progress_every == 0:
                    if show_current:
                        self.stdout.write("")
                    self.stdout.write(
                        "[p] Rows processed="
                        f"{stats['rows_seen']} imported={stats['rows_imported']} "
                        f"updated={stats['rows_updated']} skipped={stats['rows_skipped']} "
                        f"current={current_compound_label} -> {current_target_label}"
                    )
                    checkpoint_data.setdefault("sources", {})[source_key] = {
                        "source": source,
                        "path": str(path),
                        "signature": source_signature,
                        "rows_completed": source_rows,
                    }
                    self._save_checkpoint_file(checkpoint_file, checkpoint_data)
            if pending_parsed:
                self._process_parsed_batch(
                    source=source,
                    source_label=source_label,
                    pending_rows=pending_parsed,
                    touched_pairs=touched_pairs,
                    stats=stats,
                    dry_run=dry_run,
                    create_missing_compounds=create_missing_compounds,
                    create_missing_targets=create_missing_targets,
                    skip_existing=skip_existing,
                )
                pending_parsed.clear()
            if show_current:
                self.stdout.write("")
            checkpoint_data.setdefault("sources", {})[source_key] = {
                "source": source,
                "path": str(path),
                "signature": source_signature,
                "rows_completed": source_rows,
            }
            self._save_checkpoint_file(checkpoint_file, checkpoint_data)
            self.stdout.write(f"[i] {source_label}: processed {source_rows} rows")

        self.stdout.write(
            "[i] Import summary: "
            f"seen={stats['rows_seen']} imported={stats['rows_imported']} "
            f"updated={stats['rows_updated']} skipped={stats['rows_skipped']} "
            f"skipped_existing={stats['rows_skipped_existing']} "
            f"resume_skipped={stats['rows_resumed_skipped']} "
            f"parse_failed={stats['rows_parse_failed']} "
            f"unknown_mechanisms={stats['unknown_mechanism_rows']} "
            f"unresolved_compound={stats['unresolved_compound']} "
            f"unresolved_target={stats['unresolved_target']} "
            f"compound_match_exact={stats['compound_match_exact']} "
            f"compound_match_alias={stats['compound_match_alias']} "
            f"compound_match_fuzzy={stats['compound_match_fuzzy']} "
            f"compound_match_smiles={stats['compound_match_smiles']} "
            f"target_match_exact={stats['target_match_exact']} "
            f"target_match_fuzzy={stats['target_match_fuzzy']}"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("[i] Dry-run complete: consensus sync/review skipped."))
            return
        if defer_consensus:
            self.stdout.write(self.style.WARNING(
                "[i] Defer-consensus enabled: skipping context consensus/CTI sync/pair rebuild."
            ))
            self.stdout.write(
                "[i] Finalize later by rerunning this import command without --defer-consensus."
            )
            return

        self.stdout.write(f"[i] Recomputing context consensus for touched pairs: {len(touched_pairs)}")
        consensus_stats = rebuild_context_consensus(
            pair_ids=touched_pairs,
            progress_every=progress_every,
            progress=self.stdout.write,
            sync_cti=sync_cti,
            generated_source="multi_source_consensus",
        )
        self.stdout.write(
            "[✓] Context consensus: "
            f"contexts={consensus_stats['contexts_total']} "
            f"created={consensus_stats['contexts_created']} "
            f"updated={consensus_stats['contexts_updated']} "
            f"deleted={consensus_stats['contexts_deleted']} "
            f"conflicts={consensus_stats['conflicts']} "
            f"low_confidence={consensus_stats['low_confidence']} "
            f"unknown={consensus_stats['unknown_consensus']}"
        )
        if sync_cti:
            self.stdout.write(
                "[✓] CTI sync from consensus: "
                f"created={consensus_stats['cti_created']} "
                f"updated={consensus_stats['cti_updated']} "
                f"deleted={consensus_stats['cti_deleted']} "
                f"skipped_existing={consensus_stats['cti_skipped_existing']} "
                f"affinity_updated={consensus_stats.get('cti_affinity_updated', 0)}"
            )

        if options["rebuild_pairs"]:
            self.stdout.write("[i] Rebuilding compound-compound pair interactions from refreshed CTIs...")
            pair_stats = rebuild_compound_pair_interactions(
                source="multi_source_consensus",
                auto_sources=("ChEMBL", "computed_shared_target", "multi_source_consensus"),
                preserve_non_auto=True,
                progress_every=max(progress_every, 1000) if progress_every else 0,
                progress=self.stdout.write,
            )
            self.stdout.write(
                "[✓] Pair rebuild: "
                f"created={pair_stats['created']} updated={pair_stats['updated']} "
                f"unchanged={pair_stats['unchanged']} skipped_curated={pair_stats['skipped_curated']}"
            )

        self._print_review_rows(limit=options["review_limit"])

    def _drugbank_allowed(self, options: dict[str, Any]) -> bool:
        if options.get("allow_drugbank"):
            return True
        return os.getenv("DRUGBANK_LICENSE_ACCEPTED", "").strip().lower() in {"1", "true", "yes"}

    def _configure_db_session_for_bulk_import(self, *, dry_run: bool) -> None:
        if dry_run or connection.vendor != "postgresql":
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET synchronous_commit TO OFF")
                cursor.execute("SET statement_timeout TO 0")
            # Migrations/data loads can leave sequences behind max(id); fix once per run.
            self._realign_primary_key_sequences()
        except Exception:
            # Best effort only; continue with defaults if unavailable.
            return

    def _realign_primary_key_sequences(self) -> None:
        self._realign_primary_key_sequence_for_model(Compound)
        self._realign_primary_key_sequence_for_model(Target)
        self._realign_primary_key_sequence_for_model(CompoundTargetInteractionEvidence)

    def _realign_primary_key_sequence_for_model(self, model: type) -> None:
        if connection.vendor != "postgresql":
            return
        table = model._meta.db_table
        pk_column = model._meta.pk.column
        qtable = connection.ops.quote_name(table)
        qpk = connection.ops.quote_name(pk_column)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [table, pk_column])
                row = cursor.fetchone()
                sequence_name = row[0] if row else None
                if not sequence_name:
                    return
                cursor.execute(
                    f"SELECT setval(%s, GREATEST((SELECT COALESCE(MAX({qpk}), 0) FROM {qtable}), 1), true)",
                    [sequence_name],
                )
        except Exception:
            # Best effort only.
            return

    def _iter_rows(self, source: str, path: Path) -> Iterator[dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, list):
                for row in payload:
                    if isinstance(row, dict):
                        yield row
                return
            if isinstance(payload, dict):
                for key in ("interactions", "data", "results", "rows"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        for row in value:
                            if isinstance(row, dict):
                                yield row
                        return
            raise CommandError(f"Unsupported JSON structure in {path}.")

        if suffix == ".zip":
            yield from self._iter_zip_rows(source, path)
            return

        if suffix == ".dmp":
            if source != "iuphar":
                raise CommandError(f"Only IUPHAR source supports .dmp files (got {path}).")
            yield from self._iter_iuphar_dmp_rows(path)
            return

        if suffix == ".sdf":
            yield from self._iter_sdf_rows(path)
            return

        if suffix not in {".csv", ".tsv", ".txt"}:
            raise CommandError(f"Unsupported file type for import: {path}")
        yield from self._iter_csv_rows(path, delimiter="\t" if suffix in {".tsv", ".txt"} else ",")

    def _iter_csv_rows(self, path: Path, *, delimiter: str) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            non_comment_lines = (
                line for line in fh
                if line.strip() and not self._is_comment_line(line)
            )
            reader = csv.DictReader(non_comment_lines, delimiter=delimiter)
            for row in reader:
                if row:
                    yield self._sanitize_row(dict(row))

    def _iter_zip_rows(self, source: str, path: Path) -> Iterator[dict[str, Any]]:
        with zipfile.ZipFile(path, "r") as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            if not members:
                return
            prioritized: list[str] = []
            for ext in (".tsv", ".csv", ".json", ".dmp", ".sdf"):
                prioritized.extend([name for name in members if name.lower().endswith(ext)])
            ordered = prioritized or members
            for member in ordered:
                suffix = Path(member).suffix.lower()
                with archive.open(member, "r") as raw_fh:
                    text_fh = io.TextIOWrapper(raw_fh, encoding="utf-8", errors="replace")
                    try:
                        if suffix in {".tsv", ".txt"}:
                            non_comment_lines = (
                                line for line in text_fh
                                if line.strip() and not self._is_comment_line(line)
                            )
                            reader = csv.DictReader(non_comment_lines, delimiter="\t")
                            for row in reader:
                                if row:
                                    yield self._sanitize_row(dict(row))
                            continue
                        if suffix == ".csv":
                            reader = csv.DictReader(text_fh, delimiter=",")
                            for row in reader:
                                if row:
                                    yield self._sanitize_row(dict(row))
                            continue
                        if suffix == ".json":
                            payload = json.load(text_fh)
                            if isinstance(payload, list):
                                for row in payload:
                                    if isinstance(row, dict):
                                        yield row
                            elif isinstance(payload, dict):
                                for key in ("interactions", "data", "results", "rows"):
                                    value = payload.get(key)
                                    if isinstance(value, list):
                                        for row in value:
                                            if isinstance(row, dict):
                                                yield row
                                        break
                            continue
                        if suffix == ".dmp":
                            raise CommandError(
                                f"Found {member} inside {path}. Extract the .dmp first and pass it directly."
                            )
                        if suffix == ".sdf":
                            yield from self._iter_sdf_rows_from_handle(text_fh)
                    finally:
                        text_fh.detach()

    def _iter_iuphar_dmp_rows(self, path: Path) -> Iterator[dict[str, Any]]:
        ligand_map = {
            row.get("ligand_id", ""): row.get("name", "")
            for row in self._iter_copy_rows_from_path(path, "ligand")
            if row.get("ligand_id")
        }
        object_map = {
            row.get("object_id", ""): row.get("name", "")
            for row in self._iter_copy_rows_from_path(path, "object")
            if row.get("object_id")
        }
        species_map = {
            row.get("species_id", ""): (
                row.get("name", "") or row.get("scientific_name", "") or row.get("short_name", "")
            )
            for row in self._iter_copy_rows_from_path(path, "species")
            if row.get("species_id")
        }
        for row in self._iter_copy_rows_from_path(path, "interaction"):
            ligand_id = row.get("ligand_id", "")
            object_id = row.get("object_id", "")
            if not ligand_id and not object_id:
                continue
            yield {
                "target": object_map.get(object_id, ""),
                "target_id": object_id,
                "ligand": ligand_map.get(ligand_id, ""),
                "ligand_id": ligand_id,
                "target_species": species_map.get(row.get("species_id", ""), ""),
                "type": row.get("type", ""),
                "action": row.get("action", ""),
                "action_comment": row.get("action_comment", ""),
                "concentration_range": row.get("concentration_range", ""),
                "affinity_units": row.get("affinity_units", ""),
                "affinity_median": row.get("affinity_median", ""),
                "original_affinity_units": row.get("original_affinity_units", ""),
                "original_affinity_relation": row.get("original_affinity_relation", ""),
                "original_affinity_median_nm": row.get("original_affinity_median_nm", ""),
                "assay_description": row.get("assay_description", ""),
                "receptor_site": row.get("receptor_site", ""),
                "ligand_context": row.get("ligand_context", ""),
                "pubmed_id": "",
                "approved": "",
                "interaction_id": row.get("interaction_id", ""),
                "assay_url": row.get("assay_url", ""),
                "target_gene_symbol": "",
            }

    def _iter_iuphar_dmp_rows_from_handle(self, fh: Iterable[str]) -> Iterator[dict[str, Any]]:
        raise CommandError("IUPHAR .dmp imports require an extracted file path, not a stream handle.")

    def _iter_copy_rows_from_path(self, path: Path, table_name: str) -> Iterator[dict[str, str]]:
        marker = f"COPY public.{table_name} ("
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            in_copy = False
            columns: list[str] = []
            for line in fh:
                if not in_copy:
                    if line.startswith(marker):
                        columns = self._parse_copy_columns(line)
                        in_copy = True
                    continue

                row_line = line.rstrip("\n")
                if row_line == r"\.":
                    return
                values = row_line.split("\t")
                row: dict[str, str] = {}
                for pos, column in enumerate(columns):
                    value = values[pos] if pos < len(values) else ""
                    row[column] = "" if value == r"\N" else self._unescape_copy_value(value)
                yield row

    def _parse_copy_columns(self, copy_line: str) -> list[str]:
        start = copy_line.find("(")
        end = copy_line.find(")", start + 1)
        if start == -1 or end == -1:
            return []
        return [part.strip() for part in copy_line[start + 1:end].split(",") if part.strip()]

    def _unescape_copy_value(self, value: str) -> str:
        return (
            value
            .replace(r"\\", "\\")
            .replace(r"\t", "\t")
            .replace(r"\n", "\n")
            .replace(r"\r", "\r")
        )

    def _iter_sdf_rows(self, path: Path) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            yield from self._iter_sdf_rows_from_handle(fh)

    def _iter_sdf_rows_from_handle(self, fh: Iterable[str]) -> Iterator[dict[str, Any]]:
        record: dict[str, str] = {}
        current_key = ""
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if line == "$$$$":
                if record:
                    yield record
                record = {}
                current_key = ""
                continue
            if line.startswith("> <") and line.endswith(">"):
                current_key = line[3:-1].strip()
                if current_key and current_key not in record:
                    record[current_key] = ""
                continue
            if current_key:
                if line:
                    existing = record.get(current_key, "")
                    record[current_key] = f"{existing}\n{line}".strip() if existing else line
                else:
                    current_key = ""

    def _blank_parsed(self) -> dict[str, str]:
        return {field: "" for field in _PARSED_FIELDS}

    def _parse_row(self, source: str, row: dict[str, Any]) -> dict[str, str]:
        if source == "iuphar":
            parsed = self._parse_iuphar_row(row)
            if parsed["compound_name"] and parsed["target_name"]:
                return parsed
            return self._parse_generic_row(source, row)
        if source == "bindingdb":
            parsed = self._parse_bindingdb_row(row)
            if parsed["compound_name"] and parsed["target_name"]:
                return parsed
            return self._parse_generic_row(source, row)
        return self._parse_generic_row(source, row)

    def _parse_generic_row(self, source: str, row: dict[str, Any]) -> dict[str, str]:
        parsed = self._blank_parsed()
        for field, aliases in _FIELD_ALIASES.items():
            parsed[field] = self._extract_first(row, aliases)

        if source in {"dgidb", "pharmgkb"} and not parsed["target_name"]:
            parsed["target_name"] = self._extract_first(row, ["gene", "gene_symbol"])
        if not parsed["target_gene_name"]:
            parsed["target_gene_name"] = self._extract_first(row, ["gene", "gene_symbol"])
        return self._finalize_affinity_fields(
            parsed,
            fallback_type="",
            fallback_value="",
            fallback_units="",
            fallback_relation="",
        )

    def _parse_bindingdb_row(self, row: dict[str, Any]) -> dict[str, str]:
        parsed = self._blank_parsed()
        parsed["source_record_id"] = self._extract_first(
            row,
            ["BindingDB Reactant_set_id", "BindingDB MonomerID", "Reactant_set_id"],
        )
        parsed["source_url"] = self._extract_first(
            row,
            ["Link to Ligand-Target Pair in BindingDB", "source_url", "url", "link"],
        )
        parsed["compound_chembl_id"] = self._extract_first(row, ["ChEMBL ID of Ligand", "compound_chembl_id"])
        parsed["compound_name"] = self._extract_first(
            row,
            ["BindingDB Ligand Name", "Ligand Name", "compound_name", "ligand_name"],
        )
        parsed["compound_smiles"] = self._extract_first(row, ["Ligand SMILES", "compound_smiles", "smiles"])
        parsed["target_name"] = self._extract_first(row, ["Target Name", "target_name"])
        parsed["target_gene_name"] = self._extract_first(row, ["Target Gene Symbol", "gene_symbol"])
        parsed["species"] = self._extract_first(
            row,
            ["Target Source Organism According to Curator or DataSource", "species", "organism"],
        )
        parsed["assay_type"] = self._extract_first(row, ["Curation/DataSource", "assay_type", "assay"])

        affinity_candidates = [
            ("Ki", self._extract_first(row, ["Ki (nM)", "Ki", "ki"])),
            ("Kd", self._extract_first(row, ["Kd (nM)", "Kd", "kd"])),
            ("IC50", self._extract_first(row, ["IC50 (nM)", "IC50", "ic50"])),
            ("EC50", self._extract_first(row, ["EC50 (nM)", "EC50", "ec50"])),
        ]
        affinity_candidates = [(metric, value) for metric, value in affinity_candidates if value]
        affinity_type, affinity_value = self._pick_best_affinity(affinity_candidates)
        parsed["affinity_type"] = affinity_type
        parsed["affinity_raw_value"] = affinity_value
        parsed["affinity_units"] = "nM" if affinity_value else ""
        parsed["affinity_relation"] = self._infer_relation(affinity_value)
        parsed["dose_concentration"] = f"{affinity_type} {affinity_value} nM".strip() if affinity_value else ""
        if affinity_value:
            parsed["mechanism_of_action"] = "binding"

        pmid = self._extract_first(row, ["PMID"])
        notes = []
        doi = self._extract_first(row, ["Article DOI", "BindingDB Entry DOI"])
        if doi:
            notes.append(doi)
        if pmid:
            notes.append(f"PMID: {pmid}")
        parsed["notes"] = "; ".join(notes)
        return parsed

    def _parse_iuphar_row(self, row: dict[str, Any]) -> dict[str, str]:
        """Parse GtoPdb interaction exports explicitly to avoid target/ligand inversion."""
        parsed = self._blank_parsed()
        target_name = self._extract_first(row, ["target"])
        target_id = self._extract_first(row, ["target_id"])
        ligand_name = self._extract_first(row, ["ligand"])
        ligand_id = self._extract_first(row, ["ligand_id"])
        pubmed_id = self._extract_first(row, ["pubmed_id"])
        interaction_id = self._extract_first(row, ["interaction_id"])
        action_type = self._extract_first(row, ["type", "action"])
        action = self._extract_first(row, ["action"])
        action_comment = self._extract_first(row, ["action_comment"])
        concentration_range = self._extract_first(row, ["concentration_range"])
        affinity_units = self._extract_first(row, ["affinity_units", "original_affinity_units"])
        affinity_median = self._extract_first(row, ["affinity_median", "original_affinity_median_nm"])
        assay_description = self._extract_first(row, ["assay_description"])
        receptor_site = self._extract_first(row, ["receptor_site"])
        ligand_context = self._extract_first(row, ["ligand_context"])
        assay_url = self._extract_first(row, ["assay_url"])
        gene_symbol = self._extract_first(row, ["target_gene_symbol", "target_gene_name"])
        original_relation = self._extract_first(row, ["original_affinity_relation"])
        original_affinity_median_nm = self._extract_first(row, ["original_affinity_median_nm"])

        notes_parts = []
        if action_comment:
            notes_parts.append(f"Action comment: {action_comment}")
        if concentration_range:
            notes_parts.append(f"Concentration range: {concentration_range}")
        if affinity_median or affinity_units:
            affinity_desc = " ".join(part for part in [affinity_median, affinity_units] if part)
            notes_parts.append(f"Affinity median: {affinity_desc}".strip())
        if receptor_site:
            notes_parts.append(f"Receptor site: {receptor_site}")
        if ligand_context:
            notes_parts.append(f"Ligand context: {ligand_context}")
        if assay_description:
            notes_parts.append(f"Assay: {assay_description}")
        if pubmed_id:
            notes_parts.append(f"PubMed: {pubmed_id}")

        source_record_parts = [part for part in [interaction_id, ligand_id, target_id, pubmed_id] if part]
        source_record_id = "|".join(source_record_parts) if source_record_parts else ""

        parsed["source_record_id"] = source_record_id
        parsed["source_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/" if pubmed_id else assay_url
        parsed["compound_name"] = ligand_name
        parsed["target_name"] = target_name
        parsed["target_gene_name"] = gene_symbol
        parsed["action_type"] = action_type
        parsed["mechanism_of_action"] = action
        parsed["evidence_level"] = "high" if self._extract_first(row, ["approved"]) == "true" else "medium"
        parsed["species"] = self._extract_first(row, ["target_species", "species"])
        parsed["assay_type"] = assay_description
        parsed["dose_concentration"] = concentration_range
        parsed["notes"] = "; ".join(notes_parts)
        parsed["affinity_type"] = self._extract_first(row, ["original_affinity_units", "affinity_units"])
        parsed["affinity_raw_value"] = original_affinity_median_nm or affinity_median
        parsed["affinity_units"] = "nM" if original_affinity_median_nm else affinity_units
        parsed["affinity_relation"] = original_relation or self._infer_relation(parsed["affinity_raw_value"])
        return self._finalize_affinity_fields(
            parsed,
            fallback_type=parsed["affinity_type"],
            fallback_value=parsed["affinity_raw_value"],
            fallback_units=parsed["affinity_units"],
            fallback_relation=parsed["affinity_relation"],
        )

    def _finalize_affinity_fields(
        self,
        parsed: dict[str, str],
        *,
        fallback_type: str,
        fallback_value: str,
        fallback_units: str,
        fallback_relation: str,
    ) -> dict[str, str]:
        parsed["affinity_type"] = parsed.get("affinity_type") or fallback_type
        parsed["affinity_raw_value"] = parsed.get("affinity_raw_value") or fallback_value
        parsed["affinity_units"] = parsed.get("affinity_units") or fallback_units
        parsed["affinity_relation"] = parsed.get("affinity_relation") or fallback_relation
        if parsed["affinity_raw_value"] and not parsed.get("dose_concentration"):
            parsed["dose_concentration"] = " ".join(
                part for part in [parsed["affinity_type"], parsed["affinity_raw_value"], parsed["affinity_units"]]
                if part
            )
        return parsed

    def _extract_affinity_from_parsed(self, parsed: dict[str, str]) -> dict[str, Any]:
        affinity_nm = self._to_nanomolar(
            raw_value=parsed.get("affinity_raw_value", ""),
            units=parsed.get("affinity_units", ""),
            affinity_type=parsed.get("affinity_type", ""),
        )
        return {
            "affinity_type": parsed.get("affinity_type", "")[:20],
            "affinity_relation": parsed.get("affinity_relation", "")[:10],
            "affinity_raw_value": parsed.get("affinity_raw_value", "")[:64],
            "affinity_units": parsed.get("affinity_units", "")[:32],
            "affinity_value_nm": affinity_nm,
        }

    def _pick_best_affinity(self, candidates: list[tuple[str, str]]) -> tuple[str, str]:
        if not candidates:
            return "", ""
        priority = {"Ki": 0, "Kd": 1, "IC50": 2, "EC50": 3}
        ranked: list[tuple[float, int, str, str]] = []
        for metric, raw in candidates:
            value = self._extract_numeric(raw)
            if value is None:
                continue
            ranked.append((value, priority.get(metric, 99), metric, raw))
        if not ranked:
            return candidates[0]
        ranked.sort(key=lambda item: (item[0], item[1]))
        _, _, metric, raw = ranked[0]
        return metric, raw

    def _infer_relation(self, raw: str) -> str:
        text = (raw or "").strip()
        if text.startswith("<="):
            return "<="
        if text.startswith(">="):
            return ">="
        if text.startswith("<"):
            return "<"
        if text.startswith(">"):
            return ">"
        if text.startswith("~") or text.startswith("≈"):
            return "~"
        return "=" if text else ""

    def _to_nanomolar(self, *, raw_value: str, units: str, affinity_type: str) -> float | None:
        number = self._extract_numeric(raw_value)
        if number is None:
            return None

        metric = (affinity_type or "").strip().lower()
        unit_text = (units or "").strip().lower()
        if unit_text in {"nm", "nanomolar", "nanomol"}:
            return max(number, 0.0)
        if unit_text in {"um", "μm", "micromolar"}:
            return max(number * 1_000, 0.0)
        if unit_text in {"mm", "millimolar"}:
            return max(number * 1_000_000, 0.0)
        if unit_text in {"pm", "picomolar"}:
            return max(number / 1_000, 0.0)
        if metric.startswith("p") or unit_text.startswith("p"):
            return max(10 ** (9 - number), 0.0)
        return None

    def _extract_first(self, row: dict[str, Any], aliases: list[str]) -> str:
        lowered = row.get("__lowered_map__")
        normalized = row.get("__normalized_map__")
        if not isinstance(lowered, dict) or not isinstance(normalized, dict):
            lowered = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
            normalized = {
                self._normalize_key(str(k)): v
                for k, v in row.items()
                if k is not None
            }
            row["__lowered_map__"] = lowered
            row["__normalized_map__"] = normalized
        for key in aliases:
            if key in row:
                return self._stringify(row.get(key))
            value = lowered.get(key.lower())
            if value is not None:
                return self._stringify(value)
            value = normalized.get(self._normalize_key(key))
            if value is not None:
                return self._stringify(value)
        return ""

    def _sanitize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in row.items():
            if key is None:
                continue
            clean_key = str(key).strip().strip('"').strip("'")
            sanitized[clean_key] = value
        return sanitized

    def _normalize_key(self, key: str) -> str:
        cleaned = key.strip().strip('"').strip("'").lower()
        cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
        return cleaned.strip("_")

    def _is_comment_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if stripped.startswith("#"):
            return True
        if stripped.startswith('"#') or stripped.startswith("'#"):
            return True
        return False

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            values = []
            for item in value:
                rendered = self._stringify(item)
                if rendered:
                    values.append(rendered)
            return "; ".join(values)
        return str(value).strip()

    def _field_max_length(self, model: type, field_name: str) -> int | None:
        cache_key = (model, field_name)
        if cache_key in self._model_field_maxlen_cache:
            return self._model_field_maxlen_cache[cache_key]
        try:
            field = model._meta.get_field(field_name)
            max_length = getattr(field, "max_length", None)
        except Exception:
            max_length = None
        self._model_field_maxlen_cache[cache_key] = max_length
        return max_length

    def _clip_char_field(self, model: type, field_name: str, value: str) -> str:
        text = (value or "").strip()
        max_length = self._field_max_length(model, field_name)
        if max_length and len(text) > max_length:
            return text[:max_length]
        return text

    def _normalize_chembl_id(self, raw_value: str, *, model: type, field_name: str = "chembl_id") -> str:
        value = self._clip_char_field(model, field_name, (raw_value or "").upper())
        if not value:
            return ""
        # Prevent non-ChEMBL foreign IDs (often long source-specific IDs) from polluting chembl_id.
        if not value.startswith("CHEMBL"):
            return ""
        return value

    def _fit_model_char_fields(self, model: type, payload: dict[str, Any]) -> dict[str, Any]:
        fitted = dict(payload)
        for key, value in list(fitted.items()):
            if not isinstance(value, str):
                continue
            max_length = self._field_max_length(model, key)
            if max_length and len(value) > max_length:
                fitted[key] = value[:max_length]
        return fitted

    def _extract_numeric(self, raw: str | None) -> float | None:
        text = (raw or "").strip()
        if not text:
            return None
        match = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None

    def _normalize_evidence_level(self, raw_level: str, *, source_default: str) -> str:
        text = raw_level.strip().lower()
        if not text:
            return source_default
        if any(marker in text for marker in ("high", "strong", "approved", "expert")):
            return "high"
        if any(marker in text for marker in ("medium", "moderate", "probable")):
            return "medium"
        if any(marker in text for marker in ("low", "weak", "preclinical", "limited")):
            return "low"
        return source_default

    def _format_current_entity_label(self, *candidates: str) -> str:
        for candidate in candidates:
            text = " ".join((candidate or "").strip().split())
            if text:
                return text[:120]
        return "unknown"

    def _build_source_row_uid(self, source_label: str, parsed: dict[str, str]) -> str:
        parts = [
            source_label.strip().lower(),
            parsed.get("source_record_id", "").strip().lower(),
            parsed.get("compound_chembl_id", "").strip().lower(),
            normalize_compound_name(parsed.get("compound_name", "")).lower(),
            self._normalize_smiles_lookup_key(parsed.get("compound_smiles", "")),
            parsed.get("target_chembl_id", "").strip().lower(),
            normalize_target_name(parsed.get("target_name", "")).lower(),
            (parsed.get("target_gene_name", "") or "").strip().lower(),
            (parsed.get("action_type", "") or "").strip().lower(),
            (parsed.get("mechanism_of_action", "") or "").strip().lower(),
            (parsed.get("species", "") or "").strip().lower(),
            (parsed.get("tissue_or_cell_line", "") or "").strip().lower(),
            (parsed.get("assay_type", "") or "").strip().lower(),
            (parsed.get("dose_concentration", "") or "").strip().lower(),
            (parsed.get("exposure_time", "") or "").strip().lower(),
            (parsed.get("route", "") or "").strip().lower(),
            (parsed.get("affinity_type", "") or "").strip().lower(),
            (parsed.get("affinity_relation", "") or "").strip().lower(),
            (parsed.get("affinity_raw_value", "") or "").strip().lower(),
            (parsed.get("affinity_units", "") or "").strip().lower(),
            (parsed.get("notes", "") or "").strip().lower()[:500],
        ]
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _source_signature(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "size": int(stat.st_size),
            "mtime": int(stat.st_mtime),
        }

    def _load_checkpoint_file(self, path: Path) -> dict[str, Any]:
        try:
            if not path.exists():
                return {"sources": {}}
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {"sources": {}}
            sources = data.get("sources")
            if not isinstance(sources, dict):
                data["sources"] = {}
            return data
        except (OSError, json.JSONDecodeError):
            return {"sources": {}}

    def _save_checkpoint_file(self, path: Path, data: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
            tmp.replace(path)
        except OSError:
            # Checkpoint writes are best-effort only.
            return

    def _process_parsed_batch(
        self,
        *,
        source: str,
        source_label: str,
        pending_rows: list[dict[str, Any]],
        touched_pairs: set[tuple[int, int]],
        stats: dict[str, int],
        dry_run: bool,
        create_missing_compounds: bool,
        create_missing_targets: bool,
        skip_existing: bool,
    ) -> None:
        if not pending_rows:
            return

        # Prevent duplicate ON CONFLICT keys inside the same INSERT ... VALUES batch.
        deduped_rows: list[dict[str, Any]] = []
        seen_row_uids: set[str] = set()
        for payload in pending_rows:
            row_uid = payload.get("row_uid", "")
            if row_uid and row_uid in seen_row_uids:
                stats["rows_skipped_existing"] += 1
                continue
            if row_uid:
                seen_row_uids.add(row_uid)
            deduped_rows.append(payload)
        pending_rows = deduped_rows
        if not pending_rows:
            return

        row_uids = [row["row_uid"] for row in pending_rows if row.get("row_uid")]
        existing_row_uids: set[str] = set()
        if row_uids and not dry_run:
            existing_row_uids = set(
                CompoundTargetInteractionEvidence.objects.filter(
                    source_row_uid__in=row_uids
                ).values_list("source_row_uid", flat=True)
            )

        evidence_records: list[dict[str, Any]] = []
        for payload in pending_rows:
            parsed = payload["parsed"]
            row_uid = payload.get("row_uid", "")

            if skip_existing and row_uid and row_uid in existing_row_uids:
                stats["rows_skipped_existing"] += 1
                continue

            affinity = self._extract_affinity_from_parsed(parsed)

            compound = self._resolve_compound(
                chembl_id=parsed["compound_chembl_id"],
                name=parsed["compound_name"],
                smiles=parsed["compound_smiles"],
                create_missing=create_missing_compounds,
                stats=stats,
            )
            if not compound:
                stats["rows_skipped"] += 1
                stats["unresolved_compound"] += 1
                continue

            target = self._resolve_target(
                chembl_id=parsed["target_chembl_id"],
                name=parsed["target_name"],
                gene_name=parsed["target_gene_name"],
                organism=parsed["species"],
                create_missing=create_missing_targets,
                stats=stats,
            )
            if not target:
                stats["rows_skipped"] += 1
                stats["unresolved_target"] += 1
                continue

            canonical = canonicalize_mechanism(
                action_type=parsed["action_type"],
                mechanism_of_action=parsed["mechanism_of_action"],
                notes=parsed["notes"],
            )
            if canonical == "unknown":
                stats["unknown_mechanism_rows"] += 1

            context_key = build_interaction_context_key(
                species=parsed["species"],
                tissue_or_cell_line=parsed["tissue_or_cell_line"],
                assay_type=parsed["assay_type"],
                dose_concentration=parsed["dose_concentration"],
                exposure_time=parsed["exposure_time"],
                route=parsed["route"],
            )
            evidence_level = self._normalize_evidence_level(
                parsed["evidence_level"],
                source_default=_SOURCE_DEFAULT_EVIDENCE[source],
            )
            evidence_weight = compute_evidence_weight(
                source=source_label,
                evidence_level=evidence_level,
                assay_type=parsed["assay_type"],
            )
            evidence_uid = build_evidence_uid(
                source=source_label,
                source_record_id=parsed["source_record_id"],
                compound_id=compound.id,
                target_id=target.id,
                canonical_mechanism=canonical,
                context_key=context_key,
                notes=parsed["notes"],
            )

            touched_pairs.add((compound.id, target.id))
            if dry_run:
                continue

            defaults = {
                "compound": compound,
                "target": target,
                "source": source_label,
                "source_record_id": parsed["source_record_id"],
                "source_url": parsed["source_url"],
                "source_row_uid": row_uid or None,
                "evidence_uid": evidence_uid,
                "raw_action_type": parsed["action_type"],
                "raw_mechanism": parsed["mechanism_of_action"],
                "canonical_mechanism": canonical,
                "species": parsed["species"],
                "tissue_or_cell_line": parsed["tissue_or_cell_line"],
                "assay_type": parsed["assay_type"],
                "dose_concentration": parsed["dose_concentration"],
                "exposure_time": parsed["exposure_time"],
                "route": parsed["route"],
                "evidence_level": evidence_level,
                "evidence_weight": evidence_weight,
                "affinity_type": affinity["affinity_type"],
                "affinity_relation": affinity["affinity_relation"],
                "affinity_raw_value": affinity["affinity_raw_value"],
                "affinity_units": affinity["affinity_units"],
                "affinity_value_nm": affinity["affinity_value_nm"],
                "notes": parsed["notes"],
                "context_key": context_key,
            }
            defaults = self._fit_model_char_fields(CompoundTargetInteractionEvidence, defaults)
            evidence_records.append(
                {
                    "row_uid": row_uid,
                    "evidence_uid": evidence_uid,
                    "defaults": defaults,
                }
            )

        if not dry_run and evidence_records:
            self._persist_evidence_records(
                records=evidence_records,
                existing_row_uids=existing_row_uids,
                stats=stats,
                skip_existing=skip_existing,
            )

    def _persist_evidence_records(
        self,
        *,
        records: list[dict[str, Any]],
        existing_row_uids: set[str],
        stats: dict[str, int],
        skip_existing: bool,
    ) -> None:
        if not records:
            return

        objects = [
            CompoundTargetInteractionEvidence(**record["defaults"])
            for record in records
        ]

        if skip_existing:
            CompoundTargetInteractionEvidence.objects.bulk_create(
                objects,
                batch_size=2000,
                ignore_conflicts=True,
            )
            stats["rows_imported"] += len(objects)
            return

        update_fields = [
            "compound",
            "target",
            "source",
            "source_record_id",
            "source_url",
            "evidence_uid",
            "raw_action_type",
            "raw_mechanism",
            "canonical_mechanism",
            "species",
            "tissue_or_cell_line",
            "assay_type",
            "dose_concentration",
            "exposure_time",
            "route",
            "evidence_level",
            "evidence_weight",
            "affinity_type",
            "affinity_relation",
            "affinity_raw_value",
            "affinity_units",
            "affinity_value_nm",
            "notes",
            "context_key",
        ]
        try:
            CompoundTargetInteractionEvidence.objects.bulk_create(
                objects,
                batch_size=2000,
                update_conflicts=True,
                update_fields=update_fields,
                unique_fields=["source_row_uid"],
            )
            for record in records:
                if record["row_uid"] and record["row_uid"] in existing_row_uids:
                    stats["rows_updated"] += 1
                else:
                    stats["rows_imported"] += 1
        except IntegrityError:
            # Conflict edge-cases (usually evidence_uid collisions from legacy imports)
            # fall back to row-wise robust upsert logic.
            for record in records:
                created = self._upsert_single_evidence(
                    defaults=record["defaults"],
                    evidence_uid=record["evidence_uid"],
                    row_uid=record["row_uid"],
                    stats=stats,
                )
                if created is True:
                    stats["rows_imported"] += 1
                elif created is False:
                    stats["rows_updated"] += 1

    def _upsert_single_evidence(
        self,
        *,
        defaults: dict[str, Any],
        evidence_uid: str,
        row_uid: str,
        stats: dict[str, int],
    ) -> bool | None:
        lookup_kwargs: dict[str, Any]
        if row_uid:
            lookup_kwargs = {"source_row_uid": row_uid}
        else:
            lookup_kwargs = {"evidence_uid": evidence_uid}
        try:
            _, created = CompoundTargetInteractionEvidence.objects.update_or_create(
                **lookup_kwargs,
                defaults=defaults,
            )
            return created
        except IntegrityError:
            obj = CompoundTargetInteractionEvidence.objects.filter(evidence_uid=evidence_uid).first()
            if obj:
                update_fields: list[str] = []
                for field_name, field_value in defaults.items():
                    if field_name == "source_row_uid":
                        continue
                    if getattr(obj, field_name) != field_value:
                        setattr(obj, field_name, field_value)
                        update_fields.append(field_name)
                desired_row_uid = defaults.get("source_row_uid")
                if desired_row_uid and not obj.source_row_uid:
                    row_uid_taken = CompoundTargetInteractionEvidence.objects.filter(
                        source_row_uid=desired_row_uid
                    ).exclude(pk=obj.pk).exists()
                    if not row_uid_taken:
                        obj.source_row_uid = desired_row_uid
                        update_fields.append("source_row_uid")
                if update_fields:
                    obj.save(update_fields=update_fields)
                return False

            fallback_defaults = dict(defaults)
            fallback_defaults["source_row_uid"] = None
            try:
                CompoundTargetInteractionEvidence.objects.create(**fallback_defaults)
                return True
            except IntegrityError:
                stats["rows_skipped_existing"] += 1
                return None

    def _resolve_compound(
        self,
        *,
        chembl_id: str,
        name: str,
        smiles: str,
        create_missing: bool,
        stats: dict[str, int] | None = None,
    ) -> Compound | None:
        self._ensure_compound_match_index()
        chembl_id = self._normalize_chembl_id(chembl_id, model=Compound)
        name = self._clip_char_field(Compound, "name", normalize_compound_name(name))
        smiles = self._clip_char_field(Compound, "smiles", (smiles or "").strip())
        smiles_key = self._normalize_smiles_lookup_key(smiles)
        cache_key = (chembl_id.lower(), name.lower(), smiles_key, bool(create_missing))
        cached = self._compound_resolve_cache.get(cache_key)
        if cached is not None:
            mode, compound_id = cached
            if mode == "none" or compound_id is None:
                return None
            compound = self._get_compound_from_cache(compound_id)
            if compound and stats is not None:
                if mode == "alias":
                    stats["compound_match_alias"] += 1
                elif mode == "fuzzy":
                    stats["compound_match_fuzzy"] += 1
                elif mode == "smiles":
                    stats["compound_match_smiles"] += 1
                elif mode == "exact":
                    stats["compound_match_exact"] += 1
            return compound

        compound = None
        if chembl_id:
            compound_id = self._compound_by_chembl_id.get(chembl_id.lower())
            compound = self._get_compound_from_cache(compound_id) if compound_id else None
            if compound is None:
                compound = Compound.objects.filter(chembl_id=chembl_id).first()
                if compound:
                    self._index_compound(compound)
            if compound:
                if stats is not None:
                    stats["compound_match_exact"] += 1
                self._hydrate_compound_identifiers(compound, chembl_id=chembl_id, name=name, smiles=smiles)
                self._compound_resolve_cache[cache_key] = ("exact", compound.id)
                return compound
        if name:
            candidates = self._compound_by_name_lc.get(name.lower(), [])
            compound = self._get_compound_from_cache(candidates[0]) if candidates else None
            if compound is None:
                compound = Compound.objects.filter(name__iexact=name).first()
                if compound:
                    self._index_compound(compound)
            if compound:
                self._hydrate_compound_identifiers(compound, chembl_id=chembl_id, name=name, smiles=smiles)
                if stats is not None:
                    stats["compound_match_exact"] += 1
                self._compound_resolve_cache[cache_key] = ("exact", compound.id)
                return compound

        if smiles:
            matched_by_smiles, _ = self._match_existing_compound_by_smiles(smiles)
            if matched_by_smiles:
                self._hydrate_compound_identifiers(
                    matched_by_smiles,
                    chembl_id=chembl_id,
                    name=name,
                    smiles=smiles,
                )
                if stats is not None:
                    stats["compound_match_smiles"] += 1
                self._compound_resolve_cache[cache_key] = ("smiles", matched_by_smiles.id)
                return matched_by_smiles

        if name and not self._disable_fuzzy_matching:
            matched_compound, mode = self._match_existing_compound(name)
            if matched_compound:
                self._hydrate_compound_identifiers(
                    matched_compound,
                    chembl_id=chembl_id,
                    name=name,
                    smiles=smiles,
                )
                if stats is not None:
                    if mode == "alias":
                        stats["compound_match_alias"] += 1
                    elif mode == "fuzzy":
                        stats["compound_match_fuzzy"] += 1
                    else:
                        stats["compound_match_exact"] += 1
                self._compound_resolve_cache[cache_key] = (mode, matched_compound.id)
                return matched_compound

        if not create_missing:
            self._compound_resolve_cache[cache_key] = ("none", None)
            return None
        try:
            if chembl_id and name:
                compound = Compound.objects.create(name=name, chembl_id=chembl_id, smiles=smiles)
                self._index_compound(compound)
                self._compound_resolve_cache[cache_key] = ("created", compound.id)
                return compound
            if name:
                compound = Compound.objects.create(name=name, smiles=smiles)
                self._index_compound(compound)
                self._compound_resolve_cache[cache_key] = ("created", compound.id)
                return compound
            if chembl_id:
                compound = Compound.objects.create(name=chembl_id, chembl_id=chembl_id, smiles=smiles)
                self._index_compound(compound)
                self._compound_resolve_cache[cache_key] = ("created", compound.id)
                return compound
            if smiles:
                smiles_key = self._normalize_smiles_lookup_key(smiles)
                generated_name = f"SMILES_{smiles_key[:24]}" if smiles_key else "Unnamed compound"
                compound = Compound.objects.create(name=generated_name, smiles=smiles)
                self._index_compound(compound)
                self._compound_resolve_cache[cache_key] = ("created", compound.id)
                return compound
        except IntegrityError:
            # Resolve collisions from pre-existing name/chembl rows.
            if chembl_id:
                compound = Compound.objects.filter(chembl_id=chembl_id).first()
                if compound:
                    self._hydrate_compound_identifiers(compound, chembl_id=chembl_id, name=name, smiles=smiles)
                    self._compound_resolve_cache[cache_key] = ("exact", compound.id)
                    return compound
            if name:
                compound = Compound.objects.filter(name__iexact=name).first()
                if compound:
                    self._hydrate_compound_identifiers(compound, chembl_id=chembl_id, name=name, smiles=smiles)
                    self._compound_resolve_cache[cache_key] = ("exact", compound.id)
                    return compound
        self._compound_resolve_cache[cache_key] = ("none", None)
        return None

    def _hydrate_compound_identifiers(
        self,
        compound: Compound,
        *,
        chembl_id: str,
        name: str,
        smiles: str,
    ) -> None:
        chembl_id = self._normalize_chembl_id(chembl_id, model=Compound)
        smiles = self._clip_char_field(Compound, "smiles", smiles)
        update_fields = []
        if chembl_id and not compound.chembl_id:
            compound.chembl_id = chembl_id
            update_fields.append("chembl_id")
        if smiles and not compound.smiles:
            compound.smiles = smiles
            update_fields.append("smiles")
        if update_fields:
            compound.save(update_fields=update_fields)
            self._index_compound(compound)
        self._append_compound_alias(compound, name)

    def _match_existing_compound(self, normalized_name: str) -> tuple[Compound | None, str]:
        self._ensure_compound_match_index()
        lookup_key = normalize_compound_lookup_key(normalized_name)
        if not lookup_key:
            return None, "none"

        cached = self._compound_match_cache.get(lookup_key)
        if cached is not None:
            mode, compound_id = cached
            if compound_id is None:
                return None, mode
            return self._get_compound_from_cache(compound_id), mode

        exact_candidates = self._compound_by_key.get(lookup_key, [])
        if len(exact_candidates) == 1:
            compound = self._get_compound_from_cache(exact_candidates[0])
            self._compound_match_cache[lookup_key] = ("exact", compound.id if compound else None)
            return compound, "exact"
        if len(exact_candidates) > 1:
            compound = self._select_best_exact_candidate(exact_candidates, normalized_name)
            self._compound_match_cache[lookup_key] = ("exact", compound.id if compound else None)
            if compound:
                return compound, "exact"

        alias_candidates = self._compound_by_alias_key.get(lookup_key, [])
        if len(alias_candidates) == 1:
            compound = self._get_compound_from_cache(alias_candidates[0])
            self._compound_match_cache[lookup_key] = ("alias", compound.id if compound else None)
            return compound, "alias"
        if len(alias_candidates) > 1:
            compound = self._select_best_exact_candidate(alias_candidates, normalized_name)
            self._compound_match_cache[lookup_key] = ("alias", compound.id if compound else None)
            if compound:
                return compound, "alias"

        compound = self._find_closest_compound(normalized_name, lookup_key)
        self._compound_match_cache[lookup_key] = ("fuzzy", compound.id if compound else None)
        if compound:
            return compound, "fuzzy"
        return None, "none"

    def _match_existing_compound_by_smiles(self, smiles: str) -> tuple[Compound | None, str]:
        self._ensure_compound_match_index()
        lookup_key = self._normalize_smiles_lookup_key(smiles)
        if not lookup_key:
            return None, "none"

        cached = self._compound_smiles_match_cache.get(lookup_key)
        if cached is not None:
            mode, compound_id = cached
            if compound_id is None:
                return None, mode
            return self._get_compound_from_cache(compound_id), mode

        candidates = self._compound_by_smiles_key.get(lookup_key, [])
        if len(candidates) == 1:
            compound = self._get_compound_from_cache(candidates[0])
            self._compound_smiles_match_cache[lookup_key] = ("smiles_exact", compound.id if compound else None)
            return compound, "smiles_exact"
        if len(candidates) > 1:
            compound = self._get_compound_from_cache(candidates[0])
            self._compound_smiles_match_cache[lookup_key] = ("smiles_exact", compound.id if compound else None)
            return compound, "smiles_exact"

        fuzzy = self._find_closest_compound_by_smiles(lookup_key)
        self._compound_smiles_match_cache[lookup_key] = ("smiles_fuzzy", fuzzy.id if fuzzy else None)
        if fuzzy:
            return fuzzy, "smiles_fuzzy"
        return None, "none"

    def _find_closest_compound_by_smiles(self, lookup_key: str) -> Compound | None:
        prefix = lookup_key[:6]
        candidates: list[tuple[float, int]] = []
        candidate_ids = self._compound_smiles_prefix_ids.get(prefix) if prefix else None
        if not candidate_ids:
            candidate_ids = list(self._compound_smiles_key_by_id.keys())
        for compound_id in candidate_ids:
            candidate_key = self._compound_smiles_key_by_id.get(compound_id, "")
            if not candidate_key:
                continue
            if prefix and prefix != candidate_key[:6]:
                continue
            if abs(len(candidate_key) - len(lookup_key)) > 4:
                continue
            ratio = difflib.SequenceMatcher(None, lookup_key, candidate_key).ratio()
            if ratio < 0.985:
                continue
            candidates.append((ratio, compound_id))
        if not candidates:
            return None
        candidates.sort(reverse=True, key=lambda item: item[0])
        best_score, best_id = candidates[0]
        second_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score >= 0.995:
            return self._get_compound_from_cache(best_id)
        if best_score >= 0.99 and (best_score - second_score) >= 0.003:
            return self._get_compound_from_cache(best_id)
        return None

    def _find_closest_compound(self, normalized_name: str, lookup_key: str) -> Compound | None:
        query_tokens = self._name_tokens(normalized_name)
        if not query_tokens:
            return None

        candidates: list[tuple[float, int]] = []
        prefix = lookup_key[:4]
        candidate_ids = self._compound_name_prefix_ids.get(prefix) if prefix else None
        if not candidate_ids:
            candidate_ids = list(self._compound_canonical_name.keys())
        for compound_id in candidate_ids:
            candidate_name = self._compound_canonical_name.get(compound_id, "")
            candidate_key = normalize_compound_lookup_key(candidate_name)
            if not candidate_key:
                continue
            if prefix and prefix not in candidate_key and not candidate_key.startswith(prefix):
                continue

            ratio = difflib.SequenceMatcher(None, lookup_key, candidate_key).ratio()
            token_overlap = self._token_overlap_ratio(query_tokens, self._compound_tokens.get(compound_id, set()))
            if len(query_tokens) == 1 and len(self._compound_tokens.get(compound_id, set())) == 1:
                score = ratio
            else:
                score = ratio * 0.85 + token_overlap * 0.15
            if score < 0.90:
                continue
            candidates.append((score, compound_id))

        if not candidates:
            return None
        candidates.sort(reverse=True, key=lambda item: item[0])
        best_score, best_id = candidates[0]
        second_score = candidates[1][0] if len(candidates) > 1 else 0.0

        # Conservative guardrails to avoid incorrect fuzzy merges.
        if best_score >= 0.94 and (best_score - second_score) >= 0.03:
            return self._get_compound_from_cache(best_id)
        if best_score >= 0.98:
            return self._get_compound_from_cache(best_id)
        return None

    def _select_best_exact_candidate(self, candidate_ids: list[int], normalized_name: str) -> Compound | None:
        desired = normalize_compound_name(normalized_name).lower()
        for compound_id in candidate_ids:
            candidate = self._compound_canonical_name.get(compound_id, "")
            if candidate.lower() == desired:
                return self._get_compound_from_cache(compound_id)
        return self._get_compound_from_cache(candidate_ids[0]) if candidate_ids else None

    def _ensure_compound_match_index(self) -> None:
        if self._compound_index_loaded:
            return
        self._refresh_compound_match_index()

    def _refresh_compound_match_index(self) -> None:
        self._compound_by_key = {}
        self._compound_by_alias_key = {}
        self._compound_by_smiles_key = {}
        self._compound_by_chembl_id = {}
        self._compound_by_name_lc = {}
        self._compound_canonical_name = {}
        self._compound_tokens = {}
        self._compound_smiles_key_by_id = {}
        self._compound_name_prefix_ids = {}
        self._compound_smiles_prefix_ids = {}
        self._compound_obj_cache = {}
        self._compound_match_cache = {}
        self._compound_smiles_match_cache = {}
        self._compound_resolve_cache = {}

        for compound in Compound.objects.only("id", "name", "aliases", "smiles", "chembl_id").iterator(chunk_size=10000):
            self._index_compound(compound)

        self._compound_index_loaded = True

    def _index_compound(self, compound: Compound) -> None:
        self._compound_obj_cache[compound.id] = compound
        canonical_name = normalize_compound_name(compound.name)
        self._compound_canonical_name[compound.id] = canonical_name
        self._compound_tokens[compound.id] = self._name_tokens(canonical_name)
        if compound.chembl_id:
            self._compound_by_chembl_id[compound.chembl_id.lower()] = compound.id
        if canonical_name:
            self._add_unique_id(self._compound_by_name_lc, canonical_name.lower(), compound.id)

        key = normalize_compound_lookup_key(canonical_name)
        if key:
            self._add_unique_id(self._compound_by_key, key, compound.id)
            self._add_unique_id(self._compound_name_prefix_ids, key[:4], compound.id)

        for alias in self._split_aliases(compound.aliases):
            alias_key = normalize_compound_lookup_key(alias)
            if alias_key:
                self._add_unique_id(self._compound_by_alias_key, alias_key, compound.id)

        smiles_key = self._normalize_smiles_lookup_key(compound.smiles)
        if smiles_key:
            self._compound_smiles_key_by_id[compound.id] = smiles_key
            self._add_unique_id(self._compound_by_smiles_key, smiles_key, compound.id)
            self._add_unique_id(self._compound_smiles_prefix_ids, smiles_key[:6], compound.id)
        elif compound.id in self._compound_smiles_key_by_id:
            del self._compound_smiles_key_by_id[compound.id]

        # New rows can invalidate prior misses/candidates; swap caches in O(1).
        self._compound_match_cache = {}
        self._compound_smiles_match_cache = {}
        self._compound_resolve_cache = {}

    def _add_unique_id(self, mapping: dict[str, list[int]], key: str, value: int) -> None:
        bucket = mapping.setdefault(key, [])
        if value not in bucket:
            bucket.append(value)

    def _normalize_smiles_lookup_key(self, smiles: str | None) -> str:
        if not smiles:
            return ""
        text = re.sub(r"\s+", "", smiles.strip())
        return text

    def _get_compound_from_cache(self, compound_id: int) -> Compound | None:
        compound = self._compound_obj_cache.get(compound_id)
        if compound:
            return compound
        compound = Compound.objects.filter(pk=compound_id).first()
        if compound:
            self._compound_obj_cache[compound_id] = compound
        return compound

    def _split_aliases(self, aliases: str | None) -> list[str]:
        if not aliases:
            return []
        parts = [normalize_compound_name(part) for part in aliases.split(",")]
        return [part for part in parts if part]

    def _append_compound_alias(self, compound: Compound, alias: str) -> None:
        alias = normalize_compound_name(alias)
        if not alias:
            return
        if alias.lower() == compound.name.lower():
            return

        aliases = self._split_aliases(compound.aliases)
        alias_lc = alias.lower()
        if any(existing.lower() == alias_lc for existing in aliases):
            return
        aliases.append(alias)

        # Keep field within max_length(255) without truncating existing aliases unexpectedly.
        joined = ", ".join(aliases)
        while len(joined) > 255 and aliases:
            aliases.pop()
            joined = ", ".join(aliases)
        if joined == (compound.aliases or ""):
            return
        compound.aliases = joined
        compound.save(update_fields=["aliases"])
        if self._compound_index_loaded:
            self._index_compound(compound)

    def _name_tokens(self, name: str) -> set[str]:
        text = normalize_compound_name(name).lower()
        tokens = {token for token in re.split(r"[^a-z0-9]+", text) if token}
        return tokens

    def _token_overlap_ratio(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        shared = len(left & right)
        denom = max(len(left), len(right))
        return shared / denom if denom else 0.0

    def _resolve_target(
        self,
        *,
        chembl_id: str,
        name: str,
        gene_name: str,
        organism: str,
        create_missing: bool,
        stats: dict[str, int] | None = None,
    ) -> Target | None:
        self._ensure_target_match_index()
        chembl_id = self._normalize_chembl_id(chembl_id, model=Target)
        name = self._clip_char_field(Target, "name", normalize_target_name(name))
        gene_name = self._clip_char_field(Target, "gene_name", (gene_name or "").strip())
        organism = self._clip_char_field(Target, "organism", (organism or "").strip())
        cache_key = (chembl_id.lower(), name.lower(), gene_name.lower(), organism.lower(), bool(create_missing))
        cached = self._target_resolve_cache.get(cache_key)
        if cached is not None:
            mode, target_id = cached
            if mode == "none" or target_id is None:
                return None
            target = self._get_target_from_cache(target_id)
            if target and stats is not None:
                if mode == "fuzzy":
                    stats["target_match_fuzzy"] += 1
                elif mode == "exact":
                    stats["target_match_exact"] += 1
            return target

        target = None
        if chembl_id:
            target_id = self._target_by_chembl_id.get(chembl_id.lower())
            target = self._get_target_from_cache(target_id) if target_id else None
            if target is None:
                target = Target.objects.filter(chembl_id=chembl_id).first()
                if target:
                    self._index_target(target)
            if target:
                self._hydrate_target_identifiers(target, chembl_id=chembl_id, gene_name=gene_name, organism=organism)
                if stats is not None:
                    stats["target_match_exact"] += 1
                self._target_resolve_cache[cache_key] = ("exact", target.id)
                return target
        if name:
            name_candidates = self._target_by_name_lc.get(name.lower(), [])
            target = self._get_target_from_cache(name_candidates[0]) if name_candidates else None
            if target is None:
                target = Target.objects.filter(name__iexact=name).first()
                if target:
                    self._index_target(target)
            if target:
                self._hydrate_target_identifiers(target, chembl_id=chembl_id, gene_name=gene_name, organism=organism)
                if stats is not None:
                    stats["target_match_exact"] += 1
                self._target_resolve_cache[cache_key] = ("exact", target.id)
                return target
        if gene_name:
            gene_candidates = self._target_by_gene_key.get(normalize_compound_lookup_key(gene_name), [])
            target = self._get_target_from_cache(gene_candidates[0]) if gene_candidates else None
            if target is None:
                target = Target.objects.filter(gene_name__iexact=gene_name).first()
                if target:
                    self._index_target(target)
            if target:
                self._hydrate_target_identifiers(target, chembl_id=chembl_id, gene_name=gene_name, organism=organism)
                if stats is not None:
                    stats["target_match_exact"] += 1
                self._target_resolve_cache[cache_key] = ("exact", target.id)
                return target

        if name and not self._disable_fuzzy_matching:
            target, mode = self._match_existing_target(name, gene_name=gene_name)
            if target:
                self._hydrate_target_identifiers(target, chembl_id=chembl_id, gene_name=gene_name, organism=organism)
                if stats is not None:
                    if mode == "fuzzy":
                        stats["target_match_fuzzy"] += 1
                    else:
                        stats["target_match_exact"] += 1
                self._target_resolve_cache[cache_key] = (mode, target.id)
                return target
        if not create_missing:
            self._target_resolve_cache[cache_key] = ("none", None)
            return None
        try:
            if chembl_id and name:
                target = Target.objects.create(name=name, chembl_id=chembl_id, gene_name=gene_name or None, organism=organism)
                self._index_target(target)
                self._target_resolve_cache[cache_key] = ("created", target.id)
                return target
            if name:
                target = Target.objects.create(name=name, gene_name=gene_name or None, organism=organism)
                self._index_target(target)
                self._target_resolve_cache[cache_key] = ("created", target.id)
                return target
            if chembl_id:
                target = Target.objects.create(
                    name=chembl_id,
                    chembl_id=chembl_id,
                    gene_name=gene_name or None,
                    organism=organism,
                )
                self._index_target(target)
                self._target_resolve_cache[cache_key] = ("created", target.id)
                return target
        except IntegrityError:
            if chembl_id:
                target = Target.objects.filter(chembl_id=chembl_id).first()
                if target:
                    self._hydrate_target_identifiers(target, chembl_id=chembl_id, gene_name=gene_name, organism=organism)
                    self._target_resolve_cache[cache_key] = ("exact", target.id)
                    return target
            if name:
                target = Target.objects.filter(name__iexact=name).first()
                if target:
                    self._hydrate_target_identifiers(target, chembl_id=chembl_id, gene_name=gene_name, organism=organism)
                    self._target_resolve_cache[cache_key] = ("exact", target.id)
                    return target
        self._target_resolve_cache[cache_key] = ("none", None)
        return None

    def _hydrate_target_identifiers(self, target: Target, *, chembl_id: str, gene_name: str, organism: str) -> None:
        chembl_id = self._normalize_chembl_id(chembl_id, model=Target)
        gene_name = self._clip_char_field(Target, "gene_name", gene_name)
        organism = self._clip_char_field(Target, "organism", organism)
        fields_to_update = []
        if chembl_id and not target.chembl_id:
            target.chembl_id = chembl_id
            fields_to_update.append("chembl_id")
        if gene_name and not target.gene_name:
            target.gene_name = gene_name
            fields_to_update.append("gene_name")
        if organism and not target.organism:
            target.organism = organism
            fields_to_update.append("organism")
        if fields_to_update:
            target.save(update_fields=fields_to_update)
            self._index_target(target)

    def _match_existing_target(self, name: str, *, gene_name: str = "") -> tuple[Target | None, str]:
        self._ensure_target_match_index()
        name_key = self._normalize_target_lookup_key(name)
        gene_key = normalize_compound_lookup_key(gene_name) if gene_name else ""
        cache_key = f"{name_key}|{gene_key}"
        cached = self._target_match_cache.get(cache_key)
        if cached is not None:
            mode, target_id = cached
            if target_id is None:
                return None, mode
            return self._get_target_from_cache(target_id), mode

        if gene_key:
            gene_candidates = self._target_by_gene_key.get(gene_key, [])
            if len(gene_candidates) == 1:
                target = self._get_target_from_cache(gene_candidates[0])
                self._target_match_cache[cache_key] = ("exact", target.id if target else None)
                return target, "exact"

        name_candidates = self._target_by_key.get(name_key, [])
        if len(name_candidates) == 1:
            target = self._get_target_from_cache(name_candidates[0])
            self._target_match_cache[cache_key] = ("exact", target.id if target else None)
            return target, "exact"
        if len(name_candidates) > 1:
            target = self._get_target_from_cache(name_candidates[0])
            self._target_match_cache[cache_key] = ("exact", target.id if target else None)
            return target, "exact"

        fuzzy = self._find_closest_target(name)
        self._target_match_cache[cache_key] = ("fuzzy", fuzzy.id if fuzzy else None)
        if fuzzy:
            return fuzzy, "fuzzy"
        return None, "none"

    def _find_closest_target(self, name: str) -> Target | None:
        lookup_key = self._normalize_target_lookup_key(name)
        if not lookup_key:
            return None
        query_tokens = self._target_tokenset(name)
        candidates: list[tuple[float, int]] = []
        prefix = lookup_key[:4]
        candidate_ids = self._target_name_prefix_ids.get(prefix) if prefix else None
        if not candidate_ids:
            candidate_ids = list(self._target_canonical_name.keys())
        for target_id in candidate_ids:
            candidate_name = self._target_canonical_name.get(target_id, "")
            candidate_key = self._normalize_target_lookup_key(candidate_name)
            if not candidate_key:
                continue
            if prefix and prefix not in candidate_key and not candidate_key.startswith(prefix):
                continue
            ratio = difflib.SequenceMatcher(None, lookup_key, candidate_key).ratio()
            token_overlap = self._token_overlap_ratio(query_tokens, self._target_tokens.get(target_id, set()))
            if len(query_tokens) <= 2 and len(self._target_tokens.get(target_id, set())) <= 3:
                score = ratio * 0.9 + token_overlap * 0.1
            else:
                score = ratio * 0.85 + token_overlap * 0.15
            if score < 0.9:
                continue
            candidates.append((score, target_id))
        if not candidates:
            return None
        candidates.sort(reverse=True, key=lambda item: item[0])
        best_score, best_id = candidates[0]
        second_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score >= 0.91 and (best_score - second_score) >= 0.02:
            return self._get_target_from_cache(best_id)
        if best_score >= 0.96:
            return self._get_target_from_cache(best_id)
        return None

    def _ensure_target_match_index(self) -> None:
        if self._target_index_loaded:
            return
        self._refresh_target_match_index()

    def _refresh_target_match_index(self) -> None:
        self._target_by_key = {}
        self._target_by_gene_key = {}
        self._target_by_chembl_id = {}
        self._target_by_name_lc = {}
        self._target_canonical_name = {}
        self._target_tokens = {}
        self._target_name_prefix_ids = {}
        self._target_obj_cache = {}
        self._target_match_cache = {}
        self._target_resolve_cache = {}
        for target in Target.objects.only("id", "name", "gene_name", "chembl_id").iterator(chunk_size=10000):
            self._index_target(target)
        self._target_index_loaded = True

    def _index_target(self, target: Target) -> None:
        self._target_obj_cache[target.id] = target
        canonical_name = normalize_target_name(target.name)
        self._target_canonical_name[target.id] = canonical_name
        self._target_tokens[target.id] = self._target_tokenset(canonical_name)
        if target.chembl_id:
            self._target_by_chembl_id[target.chembl_id.lower()] = target.id
        if canonical_name:
            self._add_unique_id(self._target_by_name_lc, canonical_name.lower(), target.id)
        name_key = self._normalize_target_lookup_key(canonical_name)
        if name_key:
            self._add_unique_id(self._target_by_key, name_key, target.id)
            self._add_unique_id(self._target_name_prefix_ids, name_key[:4], target.id)
        if target.gene_name:
            gene_key = normalize_compound_lookup_key(target.gene_name)
            if gene_key:
                self._add_unique_id(self._target_by_gene_key, gene_key, target.id)
        # New rows can invalidate prior misses/candidates; swap cache in O(1).
        self._target_match_cache = {}
        self._target_resolve_cache = {}

    def _get_target_from_cache(self, target_id: int) -> Target | None:
        target = self._target_obj_cache.get(target_id)
        if target:
            return target
        target = Target.objects.filter(pk=target_id).first()
        if target:
            self._target_obj_cache[target_id] = target
        return target

    def _normalize_target_lookup_key(self, raw: str | None) -> str:
        normalized = normalize_target_name(raw).lower()
        return re.sub(r"[^a-z0-9]+", "", normalized)

    def _target_tokenset(self, name: str) -> set[str]:
        text = normalize_target_name(name).lower()
        text = text.replace("5-ht", "5ht")
        return {token for token in re.split(r"[^a-z0-9]+", text) if token}

    def _print_review_rows(self, *, limit: int):
        rows = get_context_review_rows(limit=limit)
        self.stdout.write(f"[i] Review rows (low-confidence/conflict/unknown): {len(rows)}")
        if not rows:
            return
        for row in rows:
            self.stdout.write(
                "  - "
                f"{row.compound.name} -> {row.target.name} | mech={row.consensus_mechanism} "
                f"conf={row.consensus_confidence} conflict={row.has_conflict} "
                f"evidence={row.evidence_count} reason={row.unresolved_reason or '-'} "
                f"context={row.context_key}"
            )
