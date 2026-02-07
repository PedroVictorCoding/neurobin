"""Shared mechanism normalization and interaction inference engine."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from time import perf_counter

from .models import CompoundTargetInteraction, CompoundToCompoundTargetInteraction


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
