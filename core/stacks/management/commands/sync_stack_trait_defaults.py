from __future__ import annotations

from django.core.management.base import BaseCommand

from stacks.models import MechanismTraitRule, StackTrait
from stacks.trait_engine import DEFAULT_RULES, DEFAULT_TRAITS


class Command(BaseCommand):
    help = "Seed or refresh default stack trait definitions and mechanism-to-trait rules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace-rules",
            action="store_true",
            help="Remove existing rules before importing defaults.",
        )

    def handle(self, *args, **options):
        replace_rules = options.get("replace_rules", False)
        trait_created = 0
        trait_updated = 0
        rule_created = 0
        rule_updated = 0

        traits_by_slug = {}
        for row in DEFAULT_TRAITS:
            trait, created = StackTrait.objects.update_or_create(
                slug=row["slug"],
                defaults={
                    "label": row["label"],
                    "trait_type": row["trait_type"],
                    "description": row.get("description", ""),
                    "is_hypothesis": row.get("is_hypothesis", False),
                    "min_score": row.get("min_score", -5.0),
                    "max_score": row.get("max_score", 5.0),
                    "default_weight": row.get("default_weight", 1.0),
                    "display_order": row.get("display_order", 0),
                    "is_active": True,
                },
            )
            traits_by_slug[trait.slug] = trait
            if created:
                trait_created += 1
            else:
                trait_updated += 1

        if replace_rules:
            deleted, _ = MechanismTraitRule.objects.all().delete()
            self.stdout.write(f"[i] Removed existing mechanism rules: {deleted}")

        for row in DEFAULT_RULES:
            trait = traits_by_slug.get(row["trait_slug"])
            if trait is None:
                continue
            identity = {
                "mechanism": row["mechanism"],
                "trait": trait,
                "target_name_contains": row.get("target_name_contains", ""),
                "species": row.get("species", ""),
                "assay_type": row.get("assay_type", ""),
                "route": row.get("route", ""),
                "priority": row.get("priority", 100),
            }
            rule, created = MechanismTraitRule.objects.update_or_create(
                **identity,
                defaults={
                    "delta": row["delta"],
                    "base_confidence": row.get("base_confidence", 0.7),
                    "source": row.get("source", "default"),
                    "notes": row.get("notes", ""),
                    "is_active": True,
                },
            )
            if created:
                rule_created += 1
            else:
                rule_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                "[✓] Stack trait defaults synced: "
                f"traits created={trait_created} updated={trait_updated}; "
                f"rules created={rule_created} updated={rule_updated}"
            )
        )
