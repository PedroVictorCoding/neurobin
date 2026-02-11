from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stacks.models import Stack, StackItem
from stacks.trait_engine import analyze_stack_character_sheet, parse_focus_groups, recommend_stack_builds


def _parse_key_value_pairs(pairs: list[str]) -> dict[str, float]:
    values = {}
    for raw in pairs:
        if "=" not in raw:
            raise CommandError(f"Invalid pair '{raw}'. Use key=value format.")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise CommandError(f"Invalid pair '{raw}'. Empty key.")
        try:
            numeric = float(value.strip())
        except ValueError as exc:
            raise CommandError(f"Invalid number in pair '{raw}'.") from exc
        values[key] = numeric
    return values


class Command(BaseCommand):
    help = "Suggest stack builds using trait-based mechanism/evidence scoring."

    def add_arguments(self, parser):
        parser.add_argument("--stack-id", type=int, help="Analyze an existing stack instead of searching candidates.")
        parser.add_argument(
            "--goal",
            action="append",
            default=[],
            help="Goal trait weight, repeatable. Example: --goal longevity=1.2",
        )
        parser.add_argument(
            "--max-trait",
            action="append",
            default=[],
            help="Upper bound for risk traits, repeatable. Example: --max-trait cardio_risk=2.0",
        )
        parser.add_argument("--candidate-id", action="append", type=int, default=[])
        parser.add_argument("--max-stack-size", type=int, default=4)
        parser.add_argument("--beam-width", type=int, default=12)
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument("--min-confidence", default="medium", help="low|medium|high")
        parser.add_argument("--no-cyp3a4-conflicts", action="store_true")
        parser.add_argument("--required-route", default="", help="Optional route context (e.g., oral, iv).")
        parser.add_argument(
            "--focus-group",
            action="append",
            default=[],
            help="Focus candidate discovery by group. Repeatable. Example: --focus-group ar --focus-group igf1",
        )
        parser.add_argument(
            "--min-group-score",
            type=float,
            default=0.0,
            help="Minimum signal score required for any selected focus group.",
        )
        parser.add_argument("--budget-limit", type=float, default=None, help="Optional budget constraint metadata.")
        parser.add_argument("--species", default="")
        parser.add_argument("--assay-type", default="")
        parser.add_argument("--route", default="")
        parser.add_argument(
            "--output-mode",
            default="ranked",
            help="ranked|hybrid|cloud",
        )
        parser.add_argument(
            "--include-distribution",
            action="store_true",
            help="Include candidate cloud distribution in JSON output.",
        )
        parser.add_argument("--json", action="store_true", help="Emit full JSON payload.")

    def handle(self, *args, **options):
        goals = _parse_key_value_pairs(options.get("goal") or [])
        max_traits = _parse_key_value_pairs(options.get("max_trait") or [])
        desired_context = {
            "species": options.get("species") or "",
            "assay_type": options.get("assay_type") or "",
            "route": options.get("route") or "",
        }
        constraints = {
            "max_traits": max_traits,
            "no_cyp3a4_conflicts": bool(options.get("no_cyp3a4_conflicts")),
            "required_route": options.get("required_route") or "",
            "focus_groups": parse_focus_groups(options.get("focus_group") or []),
            "min_group_score": options.get("min_group_score") or 0.0,
            "budget_limit": options.get("budget_limit"),
        }

        stack_id = options.get("stack_id")
        if stack_id:
            stack = Stack.objects.filter(id=stack_id).first()
            if not stack:
                raise CommandError(f"Stack {stack_id} not found.")
            compound_ids = list(StackItem.objects.filter(stack_id=stack.id).values_list("compound_id", flat=True))
            payload = analyze_stack_character_sheet(
                compound_ids=compound_ids,
                goals=goals,
                constraints=constraints,
                min_evidence_confidence=options.get("min_confidence") or "medium",
                desired_context=desired_context,
            )
        else:
            payload = recommend_stack_builds(
                goals=goals,
                constraints=constraints,
                candidate_compound_ids=options.get("candidate_id") or None,
                max_stack_size=options.get("max_stack_size") or 4,
                beam_width=options.get("beam_width") or 12,
                top_k=options.get("top_k") or 5,
                min_evidence_confidence=options.get("min_confidence") or "medium",
                desired_context=desired_context,
                output_mode=options.get("output_mode") or "ranked",
                include_distribution=bool(options.get("include_distribution")),
            )

        if options.get("json"):
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=False))
            return

        self.stdout.write(f"[i] {payload.get('disclaimer')}")
        recommendations = payload.get("recommendations") or []
        if recommendations:
            self.stdout.write(f"[i] Recommendations: {len(recommendations)}")
            for row in recommendations:
                compounds = ", ".join(compound["name"] for compound in row.get("compounds", []))
                self.stdout.write(
                    f"  - #{row['rank']} score={row['score']:.3f} "
                    f"goals={row['goal_score']:.3f} risks={row['risk_penalty']:.3f} "
                    f"interactions={row['interaction_penalty']:.3f} :: {compounds}"
                )
            return

        traits = (payload.get("character_sheet") or {}).get("traits") or []
        if traits:
            self.stdout.write("[i] Stack character sheet:")
            for trait in traits:
                self.stdout.write(
                    f"  - {trait['slug']}: score={trait['score']:.3f} "
                    f"confidence={trait['confidence']:.3f}"
                )
            self.stdout.write(
                f"[i] total score={payload.get('score', 0):.3f} "
                f"goal={payload.get('goal_score', 0):.3f} "
                f"risk_penalty={payload.get('risk_penalty', 0):.3f} "
                f"interaction_penalty={payload.get('interaction_penalty', 0):.3f}"
            )
