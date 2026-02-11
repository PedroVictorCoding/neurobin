"""Shared mechanism normalization and interaction inference engine."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from time import perf_counter

from django.db.models import Q

from .models import (
    CompoundTargetContextConsensus,
    CompoundTargetInteraction,
    CompoundTargetInteractionEvidence,
    CompoundToCompoundTargetInteraction,
)


_ACTION_PATTERN = re.compile(r"Action:\s*([^;]+)", re.IGNORECASE)
_MECHANISM_PATTERN = re.compile(r"Mechanism:\s*([^;]+)", re.IGNORECASE)

# Order matters. More specific patterns must appear before broad substrings.
_MECHANISM_SYNONYMS: list[tuple[str, str]] = [
    ("positive allosteric modulator", "pam"),
    ("positive modulator", "pam"),
    ("pam", "pam"),
    ("negative allosteric modulator", "nam"),
    ("negative modulator", "nam"),
    ("nam", "nam"),
    ("partial inverse agonist", "inverse_agonist"),
    ("inverse agonist", "inverse_agonist"),
    ("partial agonist", "partial_agonist"),
    ("full agonist", "agonist"),
    ("competitive antagonist", "antagonist"),
    ("non-competitive antagonist", "antagonist"),
    ("antagonist", "antagonist"),
    ("competitive inhibitor", "inhibitor"),
    ("non-competitive inhibitor", "inhibitor"),
    ("reversible inhibitor", "inhibitor"),
    ("irreversible inhibitor", "inhibitor"),
    ("inhibitor", "inhibitor"),
    ("high affinity binding", "binder"),
    ("binding agent", "binder"),
    ("binding", "binder"),
    ("binder", "binder"),
    ("releasing agent", "activator"),
    ("releaser", "activator"),
    ("channel blocker", "blocker"),
    ("blocker", "blocker"),
    ("channel opener", "opener"),
    ("opener", "opener"),
    ("activator", "activator"),
    ("substrate", "substrate"),
    ("inducer", "inducer"),
    ("stabiliser", "modulator"),
    ("stabilizer", "modulator"),
    ("stabilising", "modulator"),
    ("stabilizing", "modulator"),
    ("cross-linking agent", "inhibitor"),
    ("cross linking agent", "inhibitor"),
    ("disrupting agent", "inhibitor"),
    ("degrader", "inhibitor"),
    ("reducing agent", "modulator"),
    ("chelating agent", "modulator"),
    ("oxidative enzyme", "modulator"),
    ("proteolytic enzyme", "modulator"),
    ("vaccine antigen", "binder"),
    ("antigen", "binder"),
    ("sequestering agent", "inhibitor"),
    ("hydrolytic enzyme", "modulator"),
    ("exogenous protein", "modulator"),
    ("exogenous gene", "modulator"),
    ("modulator", "modulator"),
    ("agonist", "agonist"),
]

_VALID_MECHANISMS = {
    "agonist",
    "antagonist",
    "partial_agonist",
    "inverse_agonist",
    "pam",
    "nam",
    "inhibitor",
    "inducer",
    "activator",
    "binder",
    "substrate",
    "modulator",
    "blocker",
    "opener",
    "unknown",
}

_ACTIVATING_MECHANISMS = {"agonist", "partial_agonist", "activator", "opener", "inducer", "pam"}
_INHIBITING_MECHANISMS = {"antagonist", "inverse_agonist", "inhibitor", "blocker", "nam"}
_MODULATORY_MECHANISMS = {"modulator"}
_METABOLIC_MECHANISMS = {"substrate"}
_BINDING_MECHANISMS = {"binder"}
_EVIDENCE_LEVEL_WEIGHTS = {
    "high": 1.0,
    "medium": 0.75,
    "low": 0.5,
    "unknown": 0.6,
}
_SOURCE_WEIGHTS = {
    "iuphar": 1.0,
    "drugbank": 0.95,
    "pharmgkb": 0.9,
    "bindingdb": 0.8,
    "dgidb": 0.75,
    "chembl": 0.85,
}


def affinity_level_from_nm(value_nm: float | None) -> str:
    """Map normalized nM affinity to CompoundTargetInteraction affinity levels."""
    if value_nm is None:
        return "unknown"
    if value_nm <= 10:
        return "very_high"
    if value_nm <= 100:
        return "high"
    if value_nm <= 1000:
        return "medium"
    if value_nm <= 10000:
        return "low"
    return "very_low"


def _normalize_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.lower().strip()
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    return " ".join(text.split())


def _extract_action_from_notes(notes: str | None) -> str:
    if not notes:
        return ""
    match = _ACTION_PATTERN.search(notes)
    return match.group(1).strip() if match else ""


def _extract_mechanism_from_notes(notes: str | None) -> str:
    if not notes:
        return ""
    match = _MECHANISM_PATTERN.search(notes)
    return match.group(1).strip() if match else ""


def _map_candidate(candidate: str | None) -> str:
    text = _normalize_text(candidate)
    if not text:
        return "unknown"

    underscored = text.replace(" ", "_")
    if underscored in _VALID_MECHANISMS:
        return underscored

    for phrase, canonical in _MECHANISM_SYNONYMS:
        if phrase in text:
            return canonical
    return "unknown"


def canonicalize_mechanism(
    *,
    action_type: str | None = None,
    mechanism_of_action: str | None = None,
    notes: str | None = None,
) -> str:
    """
    Canonical mechanism mapper used across all import paths.

    Priority:
    1) action_type
    2) mechanism_of_action
    3) notes Action: ...
    4) notes Mechanism: ...
    5) full notes fallback
    """
    ordered_candidates = [
        action_type,
        mechanism_of_action,
        _extract_action_from_notes(notes),
        _extract_mechanism_from_notes(notes),
        notes,
    ]
    for candidate in ordered_candidates:
        mapped = _map_candidate(candidate)
        if mapped != "unknown":
            return mapped
    return "unknown"


def normalize_context_value(value: str | None) -> str:
    return _normalize_text(value) or "unspecified"


def build_interaction_context_key(
    *,
    species: str | None = None,
    tissue_or_cell_line: str | None = None,
    assay_type: str | None = None,
    dose_concentration: str | None = None,
    exposure_time: str | None = None,
    route: str | None = None,
) -> str:
    parts = [
        normalize_context_value(species),
        normalize_context_value(tissue_or_cell_line),
        normalize_context_value(assay_type),
        normalize_context_value(dose_concentration),
        normalize_context_value(exposure_time),
        normalize_context_value(route),
    ]
    return "|".join(parts)


def compute_evidence_weight(
    *,
    source: str | None,
    evidence_level: str | None,
    assay_type: str | None = None,
) -> float:
    source_weight = _SOURCE_WEIGHTS.get(_normalize_text(source), 0.65)
    level_weight = _EVIDENCE_LEVEL_WEIGHTS.get(_normalize_text(evidence_level), 0.6)

    assay = _normalize_text(assay_type)
    assay_bonus = 0.0
    if "clinical" in assay:
        assay_bonus = 0.15
    elif "in vivo" in assay:
        assay_bonus = 0.08
    elif "in vitro" in assay:
        assay_bonus = 0.03

    weight = source_weight * level_weight + assay_bonus
    return max(0.2, min(weight, 1.5))


def build_evidence_uid(
    *,
    source: str,
    source_record_id: str | None,
    compound_id: int,
    target_id: int,
    canonical_mechanism: str,
    context_key: str,
    notes: str | None = None,
) -> str:
    payload = "|".join([
        source.strip().lower(),
        (source_record_id or "").strip().lower(),
        str(compound_id),
        str(target_id),
        canonical_mechanism.strip().lower(),
        context_key.strip().lower(),
        (notes or "").strip().lower()[:200],
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_context_consensus(
    evidences: Iterable[CompoundTargetInteractionEvidence],
) -> dict[str, object]:
    evidence_list = list(evidences)
    if not evidence_list:
        return {
            "consensus_mechanism": "unknown",
            "consensus_confidence": "low",
            "has_conflict": False,
            "unresolved_reason": "no_evidence_rows",
            "evidence_count": 0,
            "total_weight": 0.0,
            "mechanism_weights": {},
            "source_breakdown": {},
        }

    mechanism_weights: Counter[str] = Counter()
    source_breakdown: Counter[str] = Counter()

    for evidence in evidence_list:
        weight = evidence.evidence_weight or compute_evidence_weight(
            source=evidence.source,
            evidence_level=evidence.evidence_level,
            assay_type=evidence.assay_type,
        )
        mechanism = (evidence.canonical_mechanism or "unknown").strip() or "unknown"
        mechanism_weights[mechanism] += float(weight)
        source_breakdown[(evidence.source or "unknown").strip() or "unknown"] += float(weight)

    non_unknown_weights = {k: v for k, v in mechanism_weights.items() if k != "unknown"}
    total_weight = float(sum(mechanism_weights.values()))
    if not non_unknown_weights:
        return {
            "consensus_mechanism": "unknown",
            "consensus_confidence": "low",
            "has_conflict": False,
            "unresolved_reason": "only_unknown_mechanisms",
            "evidence_count": len(evidence_list),
            "total_weight": total_weight,
            "mechanism_weights": dict(mechanism_weights),
            "source_breakdown": dict(source_breakdown),
        }

    ranked = sorted(non_unknown_weights.items(), key=lambda item: item[1], reverse=True)
    winner, winner_weight = ranked[0]
    second_weight = ranked[1][1] if len(ranked) > 1 else 0.0
    non_unknown_total = float(sum(non_unknown_weights.values()))
    winner_share = winner_weight / non_unknown_total if non_unknown_total else 0.0

    has_conflict = len(ranked) > 1 and second_weight > 0 and (second_weight / winner_weight) >= 0.45
    if winner_share >= 0.75 and len(evidence_list) >= 2 and not has_conflict:
        confidence = "high"
    elif winner_share >= 0.55:
        confidence = "medium"
    else:
        confidence = "low"

    unresolved_reason = ""
    if has_conflict and confidence == "low":
        unresolved_reason = "high_competition_between_mechanisms"
    elif confidence == "low":
        unresolved_reason = "weak_consensus"

    return {
        "consensus_mechanism": winner,
        "consensus_confidence": confidence,
        "has_conflict": has_conflict,
        "unresolved_reason": unresolved_reason,
        "evidence_count": len(evidence_list),
        "total_weight": total_weight,
        "mechanism_weights": dict(mechanism_weights),
        "source_breakdown": dict(source_breakdown),
    }


def rebuild_context_consensus(
    *,
    pair_ids: set[tuple[int, int]] | None = None,
    progress_every: int = 0,
    progress: Callable[[str], None] | None = None,
    sync_cti: bool = True,
    generated_source: str = "multi_source_consensus",
) -> dict[str, int]:
    """
    Recompute consensus mechanisms per compound-target-context from evidence rows.

    Optionally sync high/medium consensus results into CompoundTargetInteraction.
    """
    progress_every = max(0, progress_every)
    pair_filter = set(pair_ids or set())
    pair_context_seen: dict[tuple[int, int], set[str]] = defaultdict(set)
    pair_mechanism_context_counts: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    pair_mechanism_affinity_values: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    evidence_qs = CompoundTargetInteractionEvidence.objects.order_by(
        "compound_id",
        "target_id",
        "context_key",
        "id",
    )
    if pair_filter:
        compound_ids = sorted({compound_id for compound_id, _ in pair_filter})
        target_ids = sorted({target_id for _, target_id in pair_filter})
        evidence_qs = evidence_qs.filter(compound_id__in=compound_ids, target_id__in=target_ids)

    grouped: dict[tuple[int, int, str], list[CompoundTargetInteractionEvidence]] = defaultdict(list)
    processed_rows = 0
    for evidence in evidence_qs.iterator():
        processed_rows += 1
        pair_key = (evidence.compound_id, evidence.target_id)
        if pair_filter and pair_key not in pair_filter:
            continue
        grouped[(evidence.compound_id, evidence.target_id, evidence.context_key)].append(evidence)
        if progress and progress_every and processed_rows % progress_every == 0:
            progress(f"[p] Consensus grouping rows={processed_rows}")

    stats = {
        "contexts_created": 0,
        "contexts_updated": 0,
        "contexts_deleted": 0,
        "contexts_total": 0,
        "low_confidence": 0,
        "unknown_consensus": 0,
        "conflicts": 0,
        "cti_created": 0,
        "cti_updated": 0,
        "cti_deleted": 0,
        "cti_skipped_existing": 0,
    }

    for (compound_id, target_id, context_key), evidences in grouped.items():
        summary = compute_context_consensus(evidences)
        exemplar = evidences[0]
        pair_key = (compound_id, target_id)
        pair_context_seen[pair_key].add(context_key)

        obj, created = CompoundTargetContextConsensus.objects.update_or_create(
            compound_id=compound_id,
            target_id=target_id,
            context_key=context_key,
            defaults={
                "species": exemplar.species,
                "tissue_or_cell_line": exemplar.tissue_or_cell_line,
                "assay_type": exemplar.assay_type,
                "dose_concentration": exemplar.dose_concentration,
                "exposure_time": exemplar.exposure_time,
                "route": exemplar.route,
                "consensus_mechanism": summary["consensus_mechanism"],
                "consensus_confidence": summary["consensus_confidence"],
                "has_conflict": summary["has_conflict"],
                "unresolved_reason": summary["unresolved_reason"],
                "evidence_count": summary["evidence_count"],
                "total_weight": summary["total_weight"],
                "mechanism_weights": summary["mechanism_weights"],
                "source_breakdown": summary["source_breakdown"],
            },
        )
        if created:
            stats["contexts_created"] += 1
        else:
            stats["contexts_updated"] += 1
        stats["contexts_total"] += 1

        if summary["consensus_confidence"] == "low":
            stats["low_confidence"] += 1
        if summary["consensus_mechanism"] == "unknown":
            stats["unknown_consensus"] += 1
        if summary["has_conflict"]:
            stats["conflicts"] += 1
        if summary["consensus_mechanism"] != "unknown" and summary["consensus_confidence"] != "low":
            winner = summary["consensus_mechanism"]
            pair_mechanism_context_counts[pair_key][winner] += 1
            winner_affinities = [
                float(ev.affinity_value_nm)
                for ev in evidences
                if ev.canonical_mechanism == winner and ev.affinity_value_nm is not None
            ]
            if winner_affinities:
                pair_mechanism_affinity_values[pair_key][winner].append(min(winner_affinities))

    touched_pairs = pair_filter or set(pair_context_seen.keys())
    for compound_id, target_id in touched_pairs:
        valid_contexts = pair_context_seen.get((compound_id, target_id), set())
        stale_qs = CompoundTargetContextConsensus.objects.filter(
            compound_id=compound_id,
            target_id=target_id,
        )
        if valid_contexts:
            stale_qs = stale_qs.exclude(context_key__in=valid_contexts)
        deleted_count, _ = stale_qs.delete()
        stats["contexts_deleted"] += deleted_count

    if sync_cti and touched_pairs:
        cti_stats = sync_cti_from_context_consensus(
            pair_mechanism_context_counts=pair_mechanism_context_counts,
            pair_mechanism_affinity_values=pair_mechanism_affinity_values,
            touched_pairs=touched_pairs,
            source=generated_source,
        )
        stats.update(cti_stats)

    return stats


def sync_cti_from_context_consensus(
    *,
    pair_mechanism_context_counts: dict[tuple[int, int], Counter[str]],
    pair_mechanism_affinity_values: dict[tuple[int, int], dict[str, list[float]]] | None = None,
    touched_pairs: set[tuple[int, int]],
    source: str = "multi_source_consensus",
) -> dict[str, int]:
    """Sync high/medium context consensus mechanisms into CompoundTargetInteraction rows."""
    stats = {
        "cti_created": 0,
        "cti_updated": 0,
        "cti_deleted": 0,
        "cti_skipped_existing": 0,
        "cti_affinity_updated": 0,
    }
    affinity_values = pair_mechanism_affinity_values or {}
    for compound_id, target_id in touched_pairs:
        wanted = pair_mechanism_context_counts.get((compound_id, target_id), Counter())
        wanted_mechanisms = set(wanted.keys())

        generated_qs = CompoundTargetInteraction.objects.filter(
            compound_id=compound_id,
            target_id=target_id,
            source=source,
        )
        stale_qs = generated_qs.exclude(mechanism__in=wanted_mechanisms)
        stale_deleted, _ = stale_qs.delete()
        stats["cti_deleted"] += stale_deleted

        for mechanism in sorted(wanted_mechanisms):
            note = (
                "Consensus from non-ChEMBL evidence "
                f"(contexts={wanted[mechanism]}, min_confidence=medium)"
            )
            mechanism_affinities = affinity_values.get((compound_id, target_id), {}).get(mechanism, [])
            affinity_level = affinity_level_from_nm(min(mechanism_affinities)) if mechanism_affinities else "unknown"
            obj, created = CompoundTargetInteraction.objects.get_or_create(
                compound_id=compound_id,
                target_id=target_id,
                mechanism=mechanism,
                defaults={
                    "source": source,
                    "affinity_level": affinity_level,
                    "notes": note,
                },
            )
            if created:
                stats["cti_created"] += 1
                continue
            if obj.source == source:
                fields_to_update = []
                if obj.notes != note:
                    obj.notes = note
                    fields_to_update.append("notes")
                if obj.affinity_level != affinity_level:
                    obj.affinity_level = affinity_level
                    fields_to_update.append("affinity_level")
                    stats["cti_affinity_updated"] += 1
                if fields_to_update:
                    obj.save(update_fields=fields_to_update)
                    stats["cti_updated"] += 1
            elif obj.source != source:
                stats["cti_skipped_existing"] += 1
    return stats


def get_context_review_rows(*, limit: int = 100) -> list[CompoundTargetContextConsensus]:
    """Rows that require curation review (low confidence, unknown, or conflicting)."""
    queryset = (
        CompoundTargetContextConsensus.objects
        .select_related("compound", "target")
        .filter(
            Q(consensus_confidence="low")
            | Q(consensus_mechanism="unknown")
            | Q(has_conflict=True)
        )
        .order_by("-has_conflict", "consensus_confidence", "-evidence_count", "compound__name")
    )
    return list(queryset[: max(1, limit)])


def infer_interaction_type(mechanism1: str, mechanism2: str) -> str:
    """Infer interaction type for one mechanism pair."""
    mechanism1 = (mechanism1 or "unknown").strip()
    mechanism2 = (mechanism2 or "unknown").strip()

    if mechanism1 == mechanism2:
        if mechanism1 in _METABOLIC_MECHANISMS:
            return "competitive_metabolism"
        if mechanism1 in _BINDING_MECHANISMS:
            return "competitive"
        if mechanism1 == "unknown":
            return "unknown"
        return "additive"

    mech1_activating = mechanism1 in _ACTIVATING_MECHANISMS
    mech2_activating = mechanism2 in _ACTIVATING_MECHANISMS
    mech1_inhibiting = mechanism1 in _INHIBITING_MECHANISMS
    mech2_inhibiting = mechanism2 in _INHIBITING_MECHANISMS

    if (mechanism1 == "substrate" and mechanism2 in _INHIBITING_MECHANISMS) or (
        mechanism2 == "substrate" and mechanism1 in _INHIBITING_MECHANISMS
    ):
        return "enzyme_inhibition"

    if (mechanism1 == "substrate" and mechanism2 in {"inducer", "activator"}) or (
        mechanism2 == "substrate" and mechanism1 in {"inducer", "activator"}
    ):
        return "enzyme_induction"

    if mechanism1 == "substrate" and mechanism2 == "substrate":
        return "competitive_metabolism"

    if (mech1_activating and mech2_activating) or (mech1_inhibiting and mech2_inhibiting):
        return "synergistic"

    if (mech1_activating and mech2_inhibiting) or (mech1_inhibiting and mech2_activating):
        return "antagonistic"

    if mechanism1 in _MODULATORY_MECHANISMS or mechanism2 in _MODULATORY_MECHANISMS:
        non_mod = mechanism2 if mechanism1 in _MODULATORY_MECHANISMS else mechanism1
        if non_mod in _ACTIVATING_MECHANISMS or non_mod in _INHIBITING_MECHANISMS:
            return "synergistic"
        return "competitive"

    if mechanism1 in _BINDING_MECHANISMS or mechanism2 in _BINDING_MECHANISMS:
        return "competitive"

    if mechanism1 != "unknown" and mechanism2 != "unknown":
        return "competitive"
    return "unknown"


def infer_interaction_type_multi(mechanisms1: Iterable[str], mechanisms2: Iterable[str]) -> tuple[str, str]:
    """Infer pair interaction type and confidence from all mechanism combinations."""
    normalized_1 = sorted({(m or "").strip() for m in mechanisms1 if m})
    normalized_2 = sorted({(m or "").strip() for m in mechanisms2 if m})
    if not normalized_1 or not normalized_2:
        return "unknown", "low"

    pair_types = [
        infer_interaction_type(mech1, mech2)
        for mech1 in normalized_1
        for mech2 in normalized_2
    ]

    precedence = [
        "enzyme_inhibition",
        "competitive_metabolism",
        "enzyme_induction",
        "antagonistic",
        "synergistic",
        "additive",
        "competitive",
        "receptor_competition",
        "unknown",
    ]
    counts = Counter(pair_types)
    interaction_type = next((kind for kind in precedence if counts.get(kind)), "unknown")
    winning_count = counts.get(interaction_type, 0)
    total = len(pair_types)

    if interaction_type == "unknown":
        confidence = "low"
    elif winning_count == total and total > 1:
        confidence = "high"
    elif winning_count >= max(2, total // 2):
        confidence = "medium"
    else:
        confidence = "low"

    return interaction_type, confidence


def rebuild_compound_pair_interactions(
    *,
    source: str = "ChEMBL",
    auto_sources: tuple[str, ...] = ("ChEMBL", "computed_shared_target"),
    preserve_non_auto: bool = True,
    progress_every: int = 0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Recompute pair interactions from all compound-target mechanism rows."""
    targets_with_compounds: dict[int, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    targets = {}
    compounds = {}
    progress_every = max(0, progress_every)
    cti_row_count = 0

    interactions = (
        CompoundTargetInteraction.objects
        .select_related("compound", "target")
        .order_by("target_id", "compound_id", "mechanism")
    )
    for interaction in interactions:
        cti_row_count += 1
        targets_with_compounds[interaction.target_id][interaction.compound_id].add(interaction.mechanism)
        targets[interaction.target_id] = interaction.target
        compounds[interaction.compound_id] = interaction.compound

    eligible_target_ids = [
        target_id for target_id, compound_map in targets_with_compounds.items()
        if len(compound_map) >= 2
    ]
    estimated_pairs = sum(
        (len(targets_with_compounds[target_id]) * (len(targets_with_compounds[target_id]) - 1)) // 2
        for target_id in eligible_target_ids
    )
    if progress:
        progress(
            f"[→] Pair rebuild input: CTIs={cti_row_count} compounds={len(compounds)} "
            "across "
            f"{len(targets_with_compounds)} targets; eligible_targets={len(eligible_target_ids)}; "
            f"estimated_pairs={estimated_pairs}"
        )

    existing_index: dict[tuple[int, int, int], CompoundToCompoundTargetInteraction] = {}
    if eligible_target_ids:
        existing_rows = (
            CompoundToCompoundTargetInteraction.objects
            .filter(target_id__in=eligible_target_ids)
            .only(
                "id",
                "compound_a_id",
                "compound_b_id",
                "target_id",
                "interaction_type",
                "description",
                "confidence",
                "source",
            )
        )
        for row in existing_rows.iterator():
            a_id = min(row.compound_a_id, row.compound_b_id)
            b_id = max(row.compound_a_id, row.compound_b_id)
            key = (row.target_id, a_id, b_id)
            if key not in existing_index:
                existing_index[key] = row
        if progress:
            progress(f"[→] Loaded {len(existing_index)} existing pair interactions for reuse.")

    stats = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_curated": 0,
        "processed_pairs": 0,
    }
    created_batch: list[CompoundToCompoundTargetInteraction] = []
    updated_batch: list[CompoundToCompoundTargetInteraction] = []
    batch_size = 1000
    started = perf_counter()

    for target_id, compound_map in targets_with_compounds.items():
        if len(compound_map) < 2:
            continue
        compound_ids = sorted(compound_map.keys())

        for i in range(len(compound_ids)):
            for j in range(i + 1, len(compound_ids)):
                compound_a_id = compound_ids[i]
                compound_b_id = compound_ids[j]
                compound_a = compounds[compound_a_id]
                compound_b = compounds[compound_b_id]
                mechanisms1 = sorted(compound_map[compound_a_id])
                mechanisms2 = sorted(compound_map[compound_b_id])
                interaction_type, confidence = infer_interaction_type_multi(mechanisms1, mechanisms2)
                description = (
                    f"{compound_a.name}: {', '.join(mechanisms1)} | "
                    f"{compound_b.name}: {', '.join(mechanisms2)}"
                )

                key = (target_id, compound_a_id, compound_b_id)
                existing = existing_index.get(key)

                if existing:
                    if (
                        preserve_non_auto
                        and existing.source
                        and existing.source not in auto_sources
                    ):
                        stats["skipped_curated"] += 1
                        stats["processed_pairs"] += 1
                        if (
                            progress
                            and progress_every
                            and stats["processed_pairs"] % progress_every == 0
                        ):
                            elapsed = perf_counter() - started
                            rate = stats["processed_pairs"] / elapsed if elapsed > 0 else 0.0
                            remaining = max(estimated_pairs - stats["processed_pairs"], 0)
                            eta_seconds = int(remaining / rate) if rate > 0 else 0
                            progress(
                                "[p] Pair rebuild "
                                f"{stats['processed_pairs']}/{estimated_pairs} | "
                                f"created={stats['created']} updated={stats['updated']} "
                                f"unchanged={stats['unchanged']} skipped={stats['skipped_curated']} | "
                                f"rate={rate:.1f}/s eta={eta_seconds}s"
                            )
                        continue

                    changed = (
                        existing.interaction_type != interaction_type
                        or existing.description != description
                        or existing.confidence != confidence
                        or existing.source != source
                    )
                    if changed:
                        existing.interaction_type = interaction_type
                        existing.description = description
                        existing.confidence = confidence
                        existing.source = source
                        updated_batch.append(existing)
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                else:
                    created_batch.append(CompoundToCompoundTargetInteraction(
                        compound_a_id=compound_a_id,
                        compound_b_id=compound_b_id,
                        target_id=target_id,
                        interaction_type=interaction_type,
                        description=description,
                        confidence=confidence,
                        source=source,
                    ))
                    stats["created"] += 1

                stats["processed_pairs"] += 1
                if len(created_batch) >= batch_size:
                    CompoundToCompoundTargetInteraction.objects.bulk_create(created_batch, batch_size=batch_size)
                    created_batch.clear()
                if len(updated_batch) >= batch_size:
                    CompoundToCompoundTargetInteraction.objects.bulk_update(
                        updated_batch,
                        ["interaction_type", "description", "confidence", "source"],
                        batch_size=batch_size,
                    )
                    updated_batch.clear()

                if (
                    progress
                    and progress_every
                    and stats["processed_pairs"] % progress_every == 0
                ):
                    elapsed = perf_counter() - started
                    rate = stats["processed_pairs"] / elapsed if elapsed > 0 else 0.0
                    remaining = max(estimated_pairs - stats["processed_pairs"], 0)
                    eta_seconds = int(remaining / rate) if rate > 0 else 0
                    progress(
                        "[p] Pair rebuild "
                        f"{stats['processed_pairs']}/{estimated_pairs} | "
                        f"created={stats['created']} updated={stats['updated']} "
                        f"unchanged={stats['unchanged']} skipped={stats['skipped_curated']} | "
                        f"rate={rate:.1f}/s eta={eta_seconds}s"
                    )

    if created_batch:
        CompoundToCompoundTargetInteraction.objects.bulk_create(created_batch, batch_size=batch_size)
    if updated_batch:
        CompoundToCompoundTargetInteraction.objects.bulk_update(
            updated_batch,
            ["interaction_type", "description", "confidence", "source"],
            batch_size=batch_size,
        )
    if (
        progress
        and stats["processed_pairs"]
        and (
            not progress_every
            or stats["processed_pairs"] % progress_every != 0
        )
    ):
        elapsed = perf_counter() - started
        rate = stats["processed_pairs"] / elapsed if elapsed > 0 else 0.0
        progress(
            "[p] Pair rebuild "
            f"{stats['processed_pairs']}/{estimated_pairs} | "
            f"created={stats['created']} updated={stats['updated']} "
            f"unchanged={stats['unchanged']} skipped={stats['skipped_curated']} | "
            f"rate={rate:.1f}/s"
        )

    return stats
