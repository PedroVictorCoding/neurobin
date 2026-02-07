from __future__ import annotations

from collections import Counter
from time import perf_counter

from django.core.management.base import BaseCommand
from django.db import IntegrityError

from compounds.interaction_engine import canonicalize_mechanism, rebuild_compound_pair_interactions
from compounds.models import ActionType, CompoundTargetInteraction, CompoundToCompoundTargetInteraction


class Command(BaseCommand):
    help = (
        "Reclassify unknown compound-target mechanisms using canonical mapping "
        "(action_type > mechanism_of_action > notes Action: ...)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Only process up to N unknown interactions.",
        )
        parser.add_argument(
            "--rebuild-pairs",
            action="store_true",
            help=(
                "After reclassification, delete auto-generated compound-compound "
                "rows (sources: ChEMBL, computed_shared_target) and rebuild."
            ),
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=250,
            help="Emit progress logs every N evaluated CTIs (default: 250, 0 disables).",
        )

    def handle(self, *args, **options):
        run_started = perf_counter()
        dry_run = options["dry_run"]
        limit = options.get("limit")
        rebuild_pairs = options.get("rebuild_pairs", False)
        progress_every = max(0, options.get("progress_every") or 0)

        queryset = (
            CompoundTargetInteraction.objects
            .filter(mechanism="unknown")
            .select_related("structured_action_type")
            .order_by("id")
        )
        if limit:
            queryset = queryset[:limit]

        total = queryset.count()
        self.stdout.write(f"[i] Unknown CTIs to evaluate: {total}")
        if total == 0:
            self.stdout.write(self.style.SUCCESS("[✓] No unknown CTIs found."))
            return

        self.stdout.write("[i] Phase 1/2: reclassifying unknown CTIs...")
        to_update_count = 0
        merged_count = 0
        would_update_count = 0
        would_merge_count = 0
        promoted_action_type_count = 0
        unresolved = Counter()
        mapped_distribution = Counter()
        resolved_count = 0
        collisions_expected = 0

        interactions = list(queryset)
        self.stdout.write(f"[i] Loaded {len(interactions)} candidate CTIs into memory.")
        phase_started = perf_counter()

        for index, interaction in enumerate(interactions, start=1):
            action_name = interaction.structured_action_type.name if interaction.structured_action_type else ""
            mapped = canonicalize_mechanism(
                action_type=action_name,
                mechanism_of_action=interaction.notes,
                notes=interaction.notes,
            )

            if mapped == "unknown":
                unresolved[(interaction.notes or "").strip()[:180]] += 1
                if progress_every and index % progress_every == 0:
                    self._emit_progress(
                        index=index,
                        total=total,
                        start_time=phase_started,
                        resolved_count=resolved_count,
                        unresolved_count=index - resolved_count,
                        would_update_count=would_update_count,
                        would_merge_count=would_merge_count,
                        dry_run=dry_run,
                    )
                continue

            resolved_count += 1
            mapped_distribution[mapped] += 1
            action_type_obj = None
            if not dry_run:
                action_type_obj = self._get_or_create_action_type(mapped)

            existing = CompoundTargetInteraction.objects.filter(
                compound_id=interaction.compound_id,
                target_id=interaction.target_id,
                mechanism=mapped,
            ).exclude(pk=interaction.pk).first()

            if existing:
                collisions_expected += 1
                would_merge_count += 1
                if dry_run:
                    if progress_every and index % progress_every == 0:
                        self._emit_progress(
                            index=index,
                            total=total,
                            start_time=phase_started,
                            resolved_count=resolved_count,
                            unresolved_count=index - resolved_count,
                            would_update_count=would_update_count,
                            would_merge_count=would_merge_count,
                            dry_run=dry_run,
                        )
                    continue
                updated = self._merge_into_existing(existing, interaction, action_type_obj)
                if updated:
                    promoted_action_type_count += 1
                merged_count += 1
                if progress_every and index % progress_every == 0:
                    self._emit_progress(
                        index=index,
                        total=total,
                        start_time=phase_started,
                        resolved_count=resolved_count,
                        unresolved_count=index - resolved_count,
                        would_update_count=would_update_count,
                        would_merge_count=would_merge_count,
                        dry_run=dry_run,
                    )
                continue

            would_update_count += 1
            if dry_run:
                if progress_every and index % progress_every == 0:
                    self._emit_progress(
                        index=index,
                        total=total,
                        start_time=phase_started,
                        resolved_count=resolved_count,
                        unresolved_count=index - resolved_count,
                        would_update_count=would_update_count,
                        would_merge_count=would_merge_count,
                        dry_run=dry_run,
                    )
                continue

            interaction.mechanism = mapped
            interaction.structured_action_type = action_type_obj
            try:
                interaction.save(update_fields=["mechanism", "structured_action_type"])
                to_update_count += 1
            except IntegrityError:
                # Handle rare race/conflict the same way: merge and remove this row.
                existing = CompoundTargetInteraction.objects.filter(
                    compound_id=interaction.compound_id,
                    target_id=interaction.target_id,
                    mechanism=mapped,
                ).exclude(pk=interaction.pk).first()
                if existing:
                    updated = self._merge_into_existing(existing, interaction, action_type_obj)
                    if updated:
                        promoted_action_type_count += 1
                    merged_count += 1
                else:
                    raise
            if progress_every and index % progress_every == 0:
                self._emit_progress(
                    index=index,
                    total=total,
                    start_time=phase_started,
                    resolved_count=resolved_count,
                    unresolved_count=index - resolved_count,
                    would_update_count=would_update_count,
                    would_merge_count=would_merge_count,
                    dry_run=dry_run,
                )

        should_emit_final_progress = progress_every == 0 or (total % progress_every != 0)
        if should_emit_final_progress:
            self._emit_progress(
                index=total,
                total=total,
                start_time=phase_started,
                resolved_count=resolved_count,
                unresolved_count=total - resolved_count,
                would_update_count=would_update_count,
                would_merge_count=would_merge_count,
                dry_run=dry_run,
                force=True,
            )

        self.stdout.write(f"[i] Reclassifiable unknown CTIs: {resolved_count}")
        self.stdout.write(f"[i] Still unresolved: {total - resolved_count}")
        self.stdout.write(f"[i] Potential collisions to merge: {collisions_expected}")
        self.stdout.write(
            f"[i] {'Would update' if dry_run else 'Updated'} CTIs: "
            f"{would_update_count if dry_run else to_update_count}"
        )
        self.stdout.write(
            f"[i] {'Would merge/delete' if dry_run else 'Merged/deleted'} duplicate CTIs: "
            f"{would_merge_count if dry_run else merged_count}"
        )
        if mapped_distribution:
            self.stdout.write("[i] Top canonical mechanisms applied:")
            for mechanism, count in mapped_distribution.most_common(10):
                self.stdout.write(f"  - ({count}) {mechanism}")

        if unresolved:
            self.stdout.write("[i] Top unresolved note patterns:")
            for note, count in unresolved.most_common(20):
                preview = note or "<empty notes>"
                self.stdout.write(f"  - ({count}) {preview}")

        phase_elapsed = perf_counter() - phase_started
        self.stdout.write(f"[i] Reclassification phase completed in {self._format_duration(phase_elapsed)}.")

        if dry_run:
            self.stdout.write(self.style.WARNING("[i] Dry-run mode: no CTIs updated."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[✓] Updated {to_update_count} CTIs; merged/deleted {merged_count} duplicate collisions; "
                    f"promoted structured_action_type on {promoted_action_type_count} retained rows."
                )
            )

        if rebuild_pairs:
            self.stdout.write("[i] Phase 2/2: rebuilding compound-compound interactions...")
            rebuild_started = perf_counter()
            auto_sources = ("ChEMBL", "computed_shared_target")
            auto_qs = CompoundToCompoundTargetInteraction.objects.filter(source__in=auto_sources)
            auto_count = auto_qs.count()
            self.stdout.write(
                f"[i] Auto-generated pair rows {'to delete' if dry_run else 'deleting'}: {auto_count}"
            )

            if dry_run:
                self.stdout.write("[i] Dry-run mode: pair rows not deleted/rebuilt.")
            else:
                deleted_count, _ = auto_qs.delete()
                self.stdout.write(f"[✓] Deleted {deleted_count} auto-generated pair rows.")
                self.stdout.write("[i] Recomputing pair interactions from canonical CTIs...")

                stats = rebuild_compound_pair_interactions(
                    source="ChEMBL",
                    auto_sources=auto_sources,
                    preserve_non_auto=True,
                    progress_every=max(progress_every, 1000) if progress_every else 0,
                    progress=self.stdout.write,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        "[✓] Rebuilt pair interactions: "
                        f"created={stats['created']}, updated={stats['updated']}, "
                        f"unchanged={stats['unchanged']}, skipped_curated={stats['skipped_curated']}"
                    )
                )
                rebuild_elapsed = perf_counter() - rebuild_started
                self.stdout.write(f"[i] Pair rebuild phase completed in {self._format_duration(rebuild_elapsed)}.")

        total_elapsed = perf_counter() - run_started
        self.stdout.write(self.style.SUCCESS(f"[✓] Command completed in {self._format_duration(total_elapsed)}."))

    def _merge_into_existing(
        self,
        existing: CompoundTargetInteraction,
        duplicate_unknown: CompoundTargetInteraction,
        action_type_obj: ActionType | None,
    ) -> bool:
        """Merge metadata from duplicate unknown row into an existing canonical row, then delete duplicate."""
        changed = False

        if not existing.structured_action_type_id and action_type_obj:
            existing.structured_action_type = action_type_obj
            changed = True

        merged_notes = self._merge_notes(existing.notes, duplicate_unknown.notes)
        if merged_notes != (existing.notes or ""):
            existing.notes = merged_notes
            changed = True

        if changed:
            existing.save(update_fields=["structured_action_type", "notes"])

        duplicate_unknown.delete()
        return changed

    def _merge_notes(self, left: str | None, right: str | None) -> str:
        left_val = (left or "").strip()
        right_val = (right or "").strip()
        if not left_val:
            return right_val
        if not right_val or right_val in left_val:
            return left_val
        if left_val in right_val:
            return right_val
        return f"{left_val}\n{right_val}"

    def _get_or_create_action_type(self, mechanism: str) -> ActionType:
        category_map = {
            "agonist": "activation",
            "partial_agonist": "activation",
            "activator": "activation",
            "opener": "activation",
            "inducer": "activation",
            "pam": "activation",
            "antagonist": "inhibition",
            "inverse_agonist": "inhibition",
            "inhibitor": "inhibition",
            "blocker": "inhibition",
            "nam": "inhibition",
            "substrate": "interaction",
            "binder": "interaction",
            "modulator": "modulation",
        }
        display = mechanism.replace("_", " ").title()
        action_type, _ = ActionType.objects.get_or_create(
            name=mechanism,
            defaults={
                "display_name": display,
                "description": f"Canonical mechanism: {display}",
                "category": category_map.get(mechanism, "unknown"),
            },
        )
        return action_type

    def _emit_progress(
        self,
        *,
        index: int,
        total: int,
        start_time: float,
        resolved_count: int,
        unresolved_count: int,
        would_update_count: int,
        would_merge_count: int,
        dry_run: bool,
        force: bool = False,
    ) -> None:
        if total <= 0:
            return
        if not force and index <= 0:
            return
        elapsed = perf_counter() - start_time
        rate = index / elapsed if elapsed > 0 else 0.0
        remaining = max(total - index, 0)
        eta_seconds = (remaining / rate) if rate > 0 else 0.0
        pct = (index / total) * 100
        verb_updates = "would_update" if dry_run else "updates_planned"
        verb_merges = "would_merge" if dry_run else "merges_planned"
        self.stdout.write(
            "[p] "
            f"{index}/{total} ({pct:.1f}%) | resolved={resolved_count} unresolved={unresolved_count} | "
            f"{verb_updates}={would_update_count} {verb_merges}={would_merge_count} | "
            f"rate={rate:.1f}/s eta={self._format_duration(eta_seconds)} elapsed={self._format_duration(elapsed)}"
        )

    def _format_duration(self, seconds: float) -> str:
        whole = max(0, int(seconds))
        minutes, sec = divmod(whole, 60)
        hours, min_part = divmod(minutes, 60)
        if hours:
            return f"{hours}h {min_part}m {sec}s"
        if minutes:
            return f"{minutes}m {sec}s"
        return f"{sec}s"
