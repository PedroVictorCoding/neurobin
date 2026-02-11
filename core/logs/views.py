from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from collections import Counter, defaultdict
from itertools import combinations

from .models import IntakeLog
from .forms import IntakeLogForm
from compounds.models import Compound


_INTERACTION_BADGE_CLASSES = {
    "synergistic": "success",
    "antagonistic": "danger",
    "competitive": "warning",
    "competitive_metabolism": "danger",
    "enzyme_inhibition": "danger",
    "enzyme_induction": "warning",
    "receptor_competition": "warning",
    "additive": "info",
    "unknown": "secondary",
}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


def _pair_key(compound_a_id: int, compound_b_id: int) -> tuple[int, int]:
    return (compound_a_id, compound_b_id) if compound_a_id < compound_b_id else (compound_b_id, compound_a_id)


def _select_primary_interaction_type(interaction_counts: Counter[str]) -> str:
    if not interaction_counts:
        return "unknown"
    ranked = sorted(interaction_counts.items(), key=lambda row: (row[1], row[0]), reverse=True)
    return ranked[0][0]


def _badge_class_for_interaction(interaction_type: str) -> str:
    return _INTERACTION_BADGE_CLASSES.get(interaction_type or "unknown", "secondary")


def build_analytics_dashboard_context(user):
    from django.utils import timezone
    from compounds.interaction_engine import infer_interaction_type_multi
    from compounds.models import CompoundTargetInteraction, CompoundToCompoundTargetInteraction
    from django.db.models import Q

    logs = IntakeLog.objects.filter(user=user).order_by('-taken_at')

    # Get today's date
    today = timezone.now().date()

    # Get today's compounds
    todays_logs = IntakeLog.objects.filter(
        user=user,
        taken_at__date=today
    ).select_related('compound')

    # Build unique compounds + intake frequencies (prevents duplicate chips).
    compound_counts: Counter[int] = Counter()
    compounds_by_id: dict[int, Compound] = {}
    for log in todays_logs:
        if not log.compound_id:
            continue
        compound_counts[log.compound_id] += 1
        compounds_by_id[log.compound_id] = log.compound
    todays_compounds = [compounds_by_id[compound_id] for compound_id in compound_counts.keys()]
    todays_compound_rows = [
        {
            "compound": compounds_by_id[compound_id],
            "count": count,
        }
        for compound_id, count in compound_counts.items()
    ]

    # Find explicit compound-pair interactions among today's compounds.
    interactions = []
    known_pair_summaries = []
    inferred_pair_summaries = []
    known_pairs: set[tuple[int, int]] = set()
    compounds_with_cti: set[int] = set()
    possible_pair_count = 0
    known_pair_count = 0
    inferred_pair_count = 0
    unresolved_pair_count = 0
    interaction_coverage_percent = 0
    compounds_without_target_data = []

    if len(todays_compounds) > 1:
        compound_ids = [compound.id for compound in todays_compounds]
        possible_pair_count = (len(compound_ids) * (len(compound_ids) - 1)) // 2

        interactions = CompoundToCompoundTargetInteraction.objects.filter(
            Q(compound_a__id__in=compound_ids, compound_b__id__in=compound_ids)
        ).select_related('compound_a', 'compound_b', 'target').distinct()

        known_pair_map: dict[tuple[int, int], dict] = {}
        for interaction in interactions:
            pair = _pair_key(interaction.compound_a_id, interaction.compound_b_id)
            known_pairs.add(pair)
            current_rank = _CONFIDENCE_RANK.get(interaction.confidence or "low", 1)
            row = known_pair_map.setdefault(
                pair,
                {
                    "compound_a": compounds_by_id.get(pair[0], interaction.compound_a),
                    "compound_b": compounds_by_id.get(pair[1], interaction.compound_b),
                    "target_count": 0,
                    "targets": [],
                    "interaction_counts": Counter(),
                    "confidence": interaction.confidence or "low",
                    "confidence_rank": current_rank,
                    "description": interaction.description or "",
                },
            )
            row["target_count"] += 1
            row["interaction_counts"][interaction.interaction_type or "unknown"] += 1
            if len(row["targets"]) < 5:
                row["targets"].append(interaction.target.name)
            if current_rank > row["confidence_rank"]:
                row["confidence_rank"] = current_rank
                row["confidence"] = interaction.confidence or "low"
            if interaction.description and len(interaction.description) > len(row["description"]):
                row["description"] = interaction.description

        for row in known_pair_map.values():
            interaction_type = _select_primary_interaction_type(row["interaction_counts"])
            row["primary_interaction_type"] = interaction_type
            row["badge_class"] = _badge_class_for_interaction(interaction_type)
            row["interaction_types"] = sorted(row["interaction_counts"].keys())
            known_pair_summaries.append(row)

        known_pair_summaries.sort(
            key=lambda row: (
                row["confidence_rank"],
                row["target_count"],
                len(row["interaction_types"]),
            ),
            reverse=True,
        )

        # Infer likely interactions for unresolved pairs via shared targets/mechanisms.
        cti_rows = list(
            CompoundTargetInteraction.objects.filter(compound_id__in=compound_ids)
            .exclude(mechanism="unknown")
            .select_related("target")
            .order_by("target_id", "compound_id", "mechanism")
        )

        target_compound_mechs: dict[int, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
        target_names: dict[int, str] = {}
        for cti in cti_rows:
            target_compound_mechs[cti.target_id][cti.compound_id].add(cti.mechanism)
            compounds_with_cti.add(cti.compound_id)
            if cti.target_id not in target_names:
                target_names[cti.target_id] = cti.target.name

        inferred_map: dict[tuple[int, int], dict] = {}
        for target_id, compound_map in target_compound_mechs.items():
            target_name = target_names.get(target_id, "")
            for compound_a_id, compound_b_id in combinations(sorted(compound_map.keys()), 2):
                pair = _pair_key(compound_a_id, compound_b_id)
                if pair in known_pairs:
                    continue

                mechanisms_a = sorted(compound_map[compound_a_id])
                mechanisms_b = sorted(compound_map[compound_b_id])
                inferred_type, inferred_conf = infer_interaction_type_multi(mechanisms_a, mechanisms_b)

                row = inferred_map.setdefault(
                    pair,
                    {
                        "compound_a": compounds_by_id.get(pair[0]),
                        "compound_b": compounds_by_id.get(pair[1]),
                        "target_count": 0,
                        "shared_targets": [],
                        "interaction_counts": Counter(),
                        "confidence": inferred_conf,
                        "confidence_rank": _CONFIDENCE_RANK.get(inferred_conf, 1),
                        "mechanism_preview": [],
                    },
                )
                row["target_count"] += 1
                row["interaction_counts"][inferred_type] += 1
                if len(row["shared_targets"]) < 5:
                    if target_name and target_name not in row["shared_targets"]:
                        row["shared_targets"].append(target_name)
                if len(row["mechanism_preview"]) < 3:
                    row["mechanism_preview"].append(
                        f"{row['compound_a'].name}: {', '.join(mechanisms_a)} | "
                        f"{row['compound_b'].name}: {', '.join(mechanisms_b)}"
                    )
                new_rank = _CONFIDENCE_RANK.get(inferred_conf, 1)
                if new_rank > row["confidence_rank"]:
                    row["confidence_rank"] = new_rank
                    row["confidence"] = inferred_conf

        for row in inferred_map.values():
            interaction_type = _select_primary_interaction_type(row["interaction_counts"])
            row["primary_interaction_type"] = interaction_type
            row["badge_class"] = _badge_class_for_interaction(interaction_type)
            row["interaction_types"] = sorted(row["interaction_counts"].keys())
            inferred_pair_summaries.append(row)

        inferred_pair_summaries.sort(
            key=lambda row: (
                row["confidence_rank"],
                row["target_count"],
                len(row["interaction_types"]),
            ),
            reverse=True,
        )

        known_pair_count = len(known_pair_summaries)
        inferred_pair_count = len(inferred_pair_summaries)
        unresolved_pair_count = max(0, possible_pair_count - known_pair_count - inferred_pair_count)
        if possible_pair_count > 0:
            interaction_coverage_percent = int(
                round(((known_pair_count + inferred_pair_count) / possible_pair_count) * 100)
            )

        compounds_without_target_data = [
            compounds_by_id[compound_id]
            for compound_id in compound_ids
            if compound_id not in compounds_with_cti
        ]

    return {
        "logs": logs,
        "todays_compounds": todays_compounds,
        "todays_compound_rows": todays_compound_rows,
        "todays_interactions": interactions,
        "todays_logs": todays_logs,
        "todays_known_pair_summaries": known_pair_summaries,
        "todays_inferred_pair_summaries": inferred_pair_summaries,
        "todays_possible_pair_count": possible_pair_count,
        "todays_known_pair_count": known_pair_count,
        "todays_inferred_pair_count": inferred_pair_count,
        "todays_unresolved_pair_count": unresolved_pair_count,
        "todays_interaction_coverage_percent": interaction_coverage_percent,
        "todays_compounds_without_target_data": compounds_without_target_data,
    }


@login_required
def log_intake(request):
    # Check if a compound ID was passed in the URL
    compound_id = request.GET.get('compound')
    initial_compound = None
    
    if compound_id:
        try:
            initial_compound = get_object_or_404(Compound, id=compound_id)
        except (ValueError, Compound.DoesNotExist):
            initial_compound = None
    
    if request.method == "POST":
        form = IntakeLogForm(request.POST)
        if form.is_valid():
            intake = form.save(commit=False)
            intake.user = request.user
            intake.save()
            return redirect(f"{reverse('profile_dashboard')}?tab=analytics")
    else:
        # Pre-populate form with initial compound if provided
        initial_data = {}
        if initial_compound:
            initial_data = {
                'compound': initial_compound.id,
                'compound_search': initial_compound.name
            }
        form = IntakeLogForm(initial=initial_data)
    
    context = {
        'form': form,
        'initial_compound': initial_compound
    }
    return render(request, "logs/log_intake.html", context)

@login_required
def analytics_dashboard(request):
    return render(request, "logs/analytics_dashboard.html", build_analytics_dashboard_context(request.user))


# REST Framework ViewSets
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count
from .serializers import IntakeLogSerializer


class IntakeLogViewSet(viewsets.ModelViewSet):
    serializer_class = IntakeLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Users can only access their own logs
        queryset = IntakeLog.objects.filter(user=self.request.user).select_related('compound').prefetch_related('compound__effect_windows').order_by('-taken_at')
        
        # Apply date filtering if provided
        taken_at_gte = self.request.query_params.get('taken_at__gte')
        taken_at_lt = self.request.query_params.get('taken_at__lt')
        
        if taken_at_gte:
            queryset = queryset.filter(taken_at__gte=taken_at_gte)
        if taken_at_lt:
            queryset = queryset.filter(taken_at__lt=taken_at_lt)
            
        return queryset

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Get analytics data for user's intake logs"""
        logs = self.get_queryset()
        
        # Basic analytics
        total_logs = logs.count()
        compounds_used = logs.values('compound__name').distinct().count()
        most_used_compound = logs.values('compound__name').annotate(
            count=Count('compound')
        ).order_by('-count').first()
        
        analytics_data = {
            'total_logs': total_logs,
            'compounds_used': compounds_used,
            'most_used_compound': most_used_compound,
        }
        
        return Response(analytics_data)
