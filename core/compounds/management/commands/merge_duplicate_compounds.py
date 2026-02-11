from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from compounds.models import (
    Compound,
    CompoundADMETPrediction,
    CompoundMolPropPrediction,
    CompoundRating,
    CompoundSafetyScreening,
    CompoundTargetContextConsensus,
    CompoundTargetInteraction,
    CompoundTargetInteractionEvidence,
    CompoundToCompoundTargetInteraction,
    normalize_compound_lookup_key,
    normalize_compound_name,
)


CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


class MergeUnsafeError(Exception):
    """Raised when a duplicate cannot be merged safely without potential data loss."""


class Command(BaseCommand):
    help = (
        "Safely merge duplicate compounds detected by normalized name key. "
        "Defaults to dry-run; pass --apply to execute writes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply merges (default is dry-run).",
        )
        parser.add_argument(
            "--limit-groups",
            type=int,
            help="Process at most N duplicate groups.",
        )
        parser.add_argument(
            "--only-key",
            type=str,
            help="Process only one normalized key group (for focused merges).",
        )
        parser.add_argument(
            "--rebuild-pairs",
            action="store_true",
            help="Rebuild auto-generated compound pair interactions after merge.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        limit_groups = options.get("limit_groups")
        only_key = (options.get("only_key") or "").strip().lower()
        rebuild_pairs = options.get("rebuild_pairs", False)

        groups, pre_skipped_unsafe = self._find_mergeable_groups(only_key=only_key)
        if limit_groups:
            groups = groups[:limit_groups]

        self.stdout.write(f"[i] Mergeable duplicate groups found: {len(groups)}")
        if not groups:
            self.stdout.write(self.style.SUCCESS("[✓] Nothing to merge."))
            return

        stats = {
            "groups_seen": len(groups),
            "groups_merged": 0,
            "compounds_deleted": 0,
            "cti_merged": 0,
            "cti_reassigned": 0,
            "consensus_merged": 0,
            "consensus_reassigned": 0,
            "evidence_reassigned": 0,
            "pair_rows_updated": 0,
            "pair_rows_deleted": 0,
            "ratings_reassigned": 0,
            "ratings_merged": 0,
            "o2o_reassigned": 0,
            "o2o_deleted": 0,
            "generic_reassigned": 0,
            "skipped_unsafe_groups": pre_skipped_unsafe,
        }

        for key, compounds in groups:
            canonical = self._pick_canonical(compounds)
            duplicates = [compound for compound in compounds if compound.id != canonical.id]
            self.stdout.write(
                "[i] Group "
                f"key={key} canonical={canonical.id}:{canonical.name} "
                f"duplicates={', '.join(f'{c.id}:{c.name}' for c in duplicates)}"
            )

            if not apply_changes:
                continue

            for duplicate in duplicates:
                try:
                    merge_stats = self._merge_one_duplicate(canonical=canonical, duplicate=duplicate)
                except MergeUnsafeError as exc:
                    stats["skipped_unsafe_groups"] += 1
                    self.stdout.write(
                        f"[!] Skip duplicate {duplicate.id}:{duplicate.name} (unsafe merge): {exc}"
                    )
                    continue
                for stat_key, value in merge_stats.items():
                    stats[stat_key] += value
                stats["compounds_deleted"] += 1
            if Compound.objects.filter(id__in=[c.id for c in duplicates]).count() == 0:
                stats["groups_merged"] += 1

        if apply_changes and rebuild_pairs:
            from compounds.interaction_engine import rebuild_compound_pair_interactions

            self.stdout.write("[i] Rebuilding pair interactions after merge...")
            pair_stats = rebuild_compound_pair_interactions(
                source="multi_source_consensus",
                auto_sources=("ChEMBL", "computed_shared_target", "multi_source_consensus"),
                preserve_non_auto=True,
                progress_every=2000,
                progress=self.stdout.write,
            )
            self.stdout.write(
                "[✓] Pair rebuild: "
                f"created={pair_stats['created']} updated={pair_stats['updated']} "
                f"unchanged={pair_stats['unchanged']} skipped_curated={pair_stats['skipped_curated']}"
            )

        mode_label = "apply" if apply_changes else "dry-run"
        self.stdout.write(f"[✓] Merge scan finished ({mode_label}).")
        self.stdout.write(
            "[i] Stats: "
            f"groups_seen={stats['groups_seen']} groups_merged={stats['groups_merged']} "
            f"compounds_deleted={stats['compounds_deleted']} "
            f"cti_merged={stats['cti_merged']} cti_reassigned={stats['cti_reassigned']} "
            f"consensus_merged={stats['consensus_merged']} consensus_reassigned={stats['consensus_reassigned']} "
            f"evidence_reassigned={stats['evidence_reassigned']} "
            f"pair_rows_updated={stats['pair_rows_updated']} pair_rows_deleted={stats['pair_rows_deleted']} "
            f"ratings_reassigned={stats['ratings_reassigned']} ratings_merged={stats['ratings_merged']} "
            f"o2o_reassigned={stats['o2o_reassigned']} o2o_deleted={stats['o2o_deleted']} "
            f"generic_reassigned={stats['generic_reassigned']} "
            f"skipped_unsafe_groups={stats['skipped_unsafe_groups']}"
        )

    def _find_mergeable_groups(self, *, only_key: str) -> tuple[list[tuple[str, list[Compound]]], int]:
        grouped: dict[str, list[Compound]] = defaultdict(list)
        skipped_unsafe = 0
        for compound in Compound.objects.all().order_by("id"):
            key = normalize_compound_lookup_key(compound.name)
            if not key:
                continue
            grouped[key].append(compound)

        mergeable: list[tuple[str, list[Compound]]] = []
        for key, compounds in grouped.items():
            if len(compounds) < 2:
                continue
            if only_key and key != only_key:
                continue

            chembl_ids = {c.chembl_id.strip().upper() for c in compounds if c.chembl_id}
            if len(chembl_ids) > 1:
                self.stdout.write(
                    f"[!] Skip unsafe group key={key}: multiple ChEMBL IDs ({', '.join(sorted(chembl_ids))})"
                )
                skipped_unsafe += 1
                continue

            smiles_set = {c.smiles.strip() for c in compounds if c.smiles}
            if len(smiles_set) > 1:
                self.stdout.write(f"[!] Skip unsafe group key={key}: conflicting SMILES values")
                skipped_unsafe += 1
                continue

            mergeable.append((key, compounds))

        return mergeable, skipped_unsafe

    def _pick_canonical(self, compounds: list[Compound]) -> Compound:
        def score(compound: Compound) -> tuple[int, int, int, int]:
            alias_count = len([part for part in (compound.aliases or "").split(",") if part.strip()])
            return (
                1 if compound.chembl_id else 0,
                1 if compound.smiles else 0,
                1 if compound.description else 0,
                alias_count,
            )

        return sorted(compounds, key=lambda c: (score(c), -c.id), reverse=True)[0]

    def _merge_one_duplicate(self, *, canonical: Compound, duplicate: Compound) -> dict[str, int]:
        stats = {
            "cti_merged": 0,
            "cti_reassigned": 0,
            "consensus_merged": 0,
            "consensus_reassigned": 0,
            "evidence_reassigned": 0,
            "pair_rows_updated": 0,
            "pair_rows_deleted": 0,
            "ratings_reassigned": 0,
            "ratings_merged": 0,
            "o2o_reassigned": 0,
            "o2o_deleted": 0,
            "generic_reassigned": 0,
            "skipped_unsafe_groups": 0,
        }

        with transaction.atomic():
            # Merge simple canonical fields.
            canonical_updated = False
            if not canonical.chembl_id and duplicate.chembl_id:
                canonical.chembl_id = duplicate.chembl_id
                canonical_updated = True
            if not canonical.smiles and duplicate.smiles:
                canonical.smiles = duplicate.smiles
                canonical_updated = True
            if not canonical.description and duplicate.description:
                canonical.description = duplicate.description
                canonical_updated = True
            if canonical_updated:
                canonical.save(update_fields=["chembl_id", "smiles", "description"])

            self._merge_compound_aliases(canonical=canonical, duplicate=duplicate)
            canonical.categories.add(*duplicate.categories.all())
            canonical.mechanism_of_action.add(*duplicate.mechanism_of_action.all())

            # One-to-one rows.
            stats["o2o_reassigned"] += self._move_one_to_one(
                model=CompoundADMETPrediction, canonical=canonical, duplicate=duplicate
            )
            stats["o2o_deleted"] += self._delete_one_to_one_if_duplicate(
                model=CompoundADMETPrediction, canonical=canonical, duplicate=duplicate
            )
            stats["o2o_reassigned"] += self._move_one_to_one(
                model=CompoundMolPropPrediction, canonical=canonical, duplicate=duplicate
            )
            stats["o2o_deleted"] += self._delete_one_to_one_if_duplicate(
                model=CompoundMolPropPrediction, canonical=canonical, duplicate=duplicate
            )
            stats["o2o_reassigned"] += self._move_one_to_one(
                model=CompoundSafetyScreening, canonical=canonical, duplicate=duplicate
            )
            stats["o2o_deleted"] += self._delete_one_to_one_if_duplicate(
                model=CompoundSafetyScreening, canonical=canonical, duplicate=duplicate
            )

            # Ratings (unique_together with user).
            for rating in CompoundRating.objects.filter(compound=duplicate).order_by("id"):
                existing = CompoundRating.objects.filter(compound=canonical, user=rating.user).first()
                if existing:
                    if rating.created_at > existing.created_at:
                        existing.score = rating.score
                        if rating.comment:
                            existing.comment = rating.comment
                        existing.save(update_fields=["score", "comment"])
                    rating.delete()
                    stats["ratings_merged"] += 1
                else:
                    rating.compound = canonical
                    rating.save(update_fields=["compound"])
                    stats["ratings_reassigned"] += 1

            # Compound-target interactions.
            for cti in CompoundTargetInteraction.objects.filter(compound=duplicate).order_by("id"):
                existing = CompoundTargetInteraction.objects.filter(
                    compound=canonical,
                    target=cti.target,
                    mechanism=cti.mechanism,
                ).first()
                if existing:
                    merged_notes = self._merge_text(existing.notes, cti.notes)
                    changed = False
                    if merged_notes != (existing.notes or ""):
                        existing.notes = merged_notes
                        changed = True
                    if not existing.structured_action_type_id and cti.structured_action_type_id:
                        existing.structured_action_type = cti.structured_action_type
                        changed = True
                    if changed:
                        existing.save(update_fields=["notes", "structured_action_type"])
                    cti.delete()
                    stats["cti_merged"] += 1
                else:
                    cti.compound = canonical
                    cti.save(update_fields=["compound"])
                    stats["cti_reassigned"] += 1

            # Context consensus rows.
            for ctx in CompoundTargetContextConsensus.objects.filter(compound=duplicate).order_by("id"):
                existing = CompoundTargetContextConsensus.objects.filter(
                    compound=canonical,
                    target=ctx.target,
                    context_key=ctx.context_key,
                ).first()
                if existing:
                    self._merge_consensus_rows(existing=existing, duplicate=ctx)
                    ctx.delete()
                    stats["consensus_merged"] += 1
                else:
                    ctx.compound = canonical
                    ctx.save(update_fields=["compound"])
                    stats["consensus_reassigned"] += 1

            # Evidence rows.
            evidence_qs = CompoundTargetInteractionEvidence.objects.filter(compound=duplicate)
            stats["evidence_reassigned"] += evidence_qs.update(compound=canonical)

            # Pair interactions referencing this compound.
            pair_stats = self._merge_pair_rows(canonical=canonical, duplicate=duplicate)
            stats["pair_rows_updated"] += pair_stats["updated"]
            stats["pair_rows_deleted"] += pair_stats["deleted"]

            # Generic FK fallback for other apps/models not explicitly handled.
            generic_stats = self._generic_fk_reassign(canonical=canonical, duplicate=duplicate)
            stats["generic_reassigned"] += generic_stats["moved"]
            if generic_stats["blocked"] > 0:
                raise MergeUnsafeError(
                    f"blocked foreign-key reassignments={generic_stats['blocked']}"
                )

            duplicate.delete()
        return stats

    def _merge_compound_aliases(self, *, canonical: Compound, duplicate: Compound) -> None:
        alias_parts = [part.strip() for part in (canonical.aliases or "").split(",") if part.strip()]
        seen = {part.lower() for part in alias_parts}

        def push(value: str) -> None:
            norm = normalize_compound_name(value)
            if not norm:
                return
            key = norm.lower()
            if key == canonical.name.lower() or key in seen:
                return
            alias_parts.append(norm)
            seen.add(key)

        push(duplicate.name)
        for part in (duplicate.aliases or "").split(","):
            push(part)

        joined = ", ".join(alias_parts)
        while len(joined) > 255 and alias_parts:
            alias_parts.pop()
            joined = ", ".join(alias_parts)
        if joined != (canonical.aliases or ""):
            canonical.aliases = joined
            canonical.save(update_fields=["aliases"])

    def _merge_pair_rows(self, *, canonical: Compound, duplicate: Compound) -> dict[str, int]:
        stats = {"updated": 0, "deleted": 0}
        rows = CompoundToCompoundTargetInteraction.objects.filter(
            compound_a_id=duplicate.id
        ) | CompoundToCompoundTargetInteraction.objects.filter(compound_b_id=duplicate.id)

        for row in rows.order_by("id"):
            new_a_id = canonical.id if row.compound_a_id == duplicate.id else row.compound_a_id
            new_b_id = canonical.id if row.compound_b_id == duplicate.id else row.compound_b_id

            if new_a_id == new_b_id:
                row.delete()
                stats["deleted"] += 1
                continue

            if new_a_id > new_b_id:
                new_a_id, new_b_id = new_b_id, new_a_id

            existing = CompoundToCompoundTargetInteraction.objects.filter(
                compound_a_id=new_a_id,
                compound_b_id=new_b_id,
                target_id=row.target_id,
            ).exclude(pk=row.pk).first()
            if existing:
                merged_desc = self._merge_text(existing.description, row.description)
                changed = False
                if merged_desc != (existing.description or ""):
                    existing.description = merged_desc
                    changed = True
                if CONFIDENCE_RANK.get(row.confidence, 0) > CONFIDENCE_RANK.get(existing.confidence, 0):
                    existing.confidence = row.confidence
                    changed = True
                if changed:
                    existing.save(update_fields=["description", "confidence"])
                row.delete()
                stats["deleted"] += 1
                continue

            row.compound_a_id = new_a_id
            row.compound_b_id = new_b_id
            try:
                row.save(update_fields=["compound_a", "compound_b"])
                stats["updated"] += 1
            except IntegrityError:
                row.delete()
                stats["deleted"] += 1
        return stats

    def _merge_consensus_rows(
        self,
        *,
        existing: CompoundTargetContextConsensus,
        duplicate: CompoundTargetContextConsensus,
    ) -> None:
        changed = False
        if CONFIDENCE_RANK.get(duplicate.consensus_confidence, 0) > CONFIDENCE_RANK.get(
            existing.consensus_confidence, 0
        ):
            existing.consensus_confidence = duplicate.consensus_confidence
            existing.consensus_mechanism = duplicate.consensus_mechanism
            changed = True
        merged_has_conflict = existing.has_conflict or duplicate.has_conflict
        if merged_has_conflict != existing.has_conflict:
            existing.has_conflict = merged_has_conflict
            changed = True
        merged_evidence_count = (existing.evidence_count or 0) + (duplicate.evidence_count or 0)
        if merged_evidence_count != (existing.evidence_count or 0):
            existing.evidence_count = merged_evidence_count
            changed = True
        merged_total_weight = float(existing.total_weight or 0.0) + float(duplicate.total_weight or 0.0)
        if merged_total_weight != float(existing.total_weight or 0.0):
            existing.total_weight = merged_total_weight
            changed = True

        merged_mech = self._merge_float_dict(existing.mechanism_weights or {}, duplicate.mechanism_weights or {})
        merged_source = self._merge_float_dict(existing.source_breakdown or {}, duplicate.source_breakdown or {})
        if merged_mech != (existing.mechanism_weights or {}):
            existing.mechanism_weights = merged_mech
            changed = True
        if merged_source != (existing.source_breakdown or {}):
            existing.source_breakdown = merged_source
            changed = True
        if not existing.unresolved_reason and duplicate.unresolved_reason:
            existing.unresolved_reason = duplicate.unresolved_reason
            changed = True
        if changed:
            existing.save(
                update_fields=[
                    "consensus_mechanism",
                    "consensus_confidence",
                    "has_conflict",
                    "unresolved_reason",
                    "evidence_count",
                    "total_weight",
                    "mechanism_weights",
                    "source_breakdown",
                ]
            )

    def _merge_float_dict(self, left: dict, right: dict) -> dict:
        merged: dict[str, float] = {}
        for key, value in left.items():
            merged[str(key)] = float(value)
        for key, value in right.items():
            merged[str(key)] = merged.get(str(key), 0.0) + float(value)
        return merged

    def _move_one_to_one(self, *, model, canonical: Compound, duplicate: Compound) -> int:
        dup_obj = model.objects.filter(compound=duplicate).first()
        if not dup_obj:
            return 0
        if model.objects.filter(compound=canonical).exists():
            return 0
        dup_obj.compound = canonical
        dup_obj.save(update_fields=["compound"])
        return 1

    def _delete_one_to_one_if_duplicate(self, *, model, canonical: Compound, duplicate: Compound) -> int:
        dup_obj = model.objects.filter(compound=duplicate).first()
        if not dup_obj:
            return 0
        if not model.objects.filter(compound=canonical).exists():
            return 0
        dup_obj.delete()
        return 1

    def _generic_fk_reassign(self, *, canonical: Compound, duplicate: Compound) -> dict[str, int]:
        moved = 0
        blocked = 0
        skip_models = {
            CompoundTargetInteraction,
            CompoundTargetContextConsensus,
            CompoundTargetInteractionEvidence,
            CompoundToCompoundTargetInteraction,
            CompoundRating,
            CompoundADMETPrediction,
            CompoundMolPropPrediction,
            CompoundSafetyScreening,
        }
        for relation in Compound._meta.related_objects:
            model = relation.related_model
            if model in skip_models:
                continue
            field = relation.field
            if not hasattr(field, "name"):
                continue
            field_name = field.name
            queryset = model.objects.filter(**{field_name: duplicate})
            if not queryset.exists():
                continue
            try:
                moved += queryset.update(**{field_name: canonical})
            except IntegrityError:
                local_moved = 0
                local_blocked = 0
                for row in queryset.order_by("pk"):
                    setattr(row, field_name, canonical)
                    try:
                        row.save(update_fields=[field_name])
                        local_moved += 1
                    except IntegrityError:
                        local_blocked += 1
                moved += local_moved
                blocked += local_blocked
                if local_blocked:
                    self.stdout.write(
                        f"[!] Could not safely reassign {local_blocked} row(s) for "
                        f"{model.__name__}.{field_name}; merge will be skipped."
                    )
        return {"moved": moved, "blocked": blocked}

    def _merge_text(self, left: str | None, right: str | None) -> str:
        left_val = (left or "").strip()
        right_val = (right or "").strip()
        if not left_val:
            return right_val
        if not right_val or right_val in left_val:
            return left_val
        if left_val in right_val:
            return right_val
        return f"{left_val}\n{right_val}"
