import json
from datetime import timedelta
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Sum
from django.forms import formset_factory
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from collections import Counter, defaultdict
from itertools import combinations

from .ip_analytics import refresh_abuseipdb_profile
from .models import (
    BloodworkEntry,
    BloodworkMeasurement,
    BloodworkRelatedIntake,
    IntakeLog,
    RequestIPPathStat,
    RequestIPProfile,
)
from .forms import BloodworkEntryForm, BloodworkMeasurementForm, BloodworkMeasurementFormSet, IntakeLogForm
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


COMMON_BIOMARKERS = {
    "Lipid Panel": [
        "Total Cholesterol", "LDL Cholesterol", "HDL Cholesterol",
        "Triglycerides", "Non-HDL Cholesterol", "VLDL Cholesterol",
        "LDL/HDL Ratio", "Total Cholesterol/HDL Ratio",
    ],
    "Complete Metabolic Panel": [
        "Glucose", "BUN", "Creatinine", "eGFR", "Sodium", "Potassium",
        "Chloride", "CO2", "Calcium", "Total Protein", "Albumin",
        "Total Bilirubin", "Alkaline Phosphatase", "AST", "ALT",
    ],
    "Basic Metabolic Panel": [
        "Glucose", "BUN", "Creatinine", "eGFR", "Sodium", "Potassium",
        "Chloride", "CO2", "Calcium",
    ],
    "CBC": [
        "WBC", "RBC", "Hemoglobin", "Hematocrit", "MCV", "MCH", "MCHC",
        "RDW", "Platelets", "Neutrophils", "Lymphocytes", "Monocytes",
        "Eosinophils", "Basophils",
    ],
    "Thyroid": [
        "TSH", "Free T4", "Free T3", "Total T4", "Total T3",
        "Reverse T3", "TPO Antibodies", "Thyroglobulin Antibodies",
    ],
    "Hormones": [
        "Total Testosterone", "Free Testosterone", "SHBG",
        "Estradiol (E2)", "LH", "FSH", "Prolactin", "DHEA-S",
        "Progesterone", "IGF-1", "Growth Hormone", "Cortisol", "ACTH", "DHT",
    ],
    "Inflammation / Immune": [
        "CRP", "hs-CRP", "ESR", "Fibrinogen", "IL-6",
        "Homocysteine", "Ferritin", "Iron", "TIBC",
    ],
    "Vitamins / Minerals": [
        "Vitamin D (25-OH)", "Vitamin B12", "Folate", "Magnesium",
        "Zinc", "Copper", "Selenium", "Vitamin A", "Vitamin E", "CoQ10",
    ],
}
_ALL_MARKERS_FLAT = sorted({name for names in COMMON_BIOMARKERS.values() for name in names})


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


def _measurement_rows_from_formset(measurement_formset):
    rows = []
    for index, form in enumerate(measurement_formset.forms):
        cleaned_data = getattr(form, "cleaned_data", None) or {}
        marker_name = (cleaned_data.get("marker_name") or "").strip()
        value = cleaned_data.get("value")
        unit = (cleaned_data.get("unit") or "").strip()
        reference_low = cleaned_data.get("reference_low")
        reference_high = cleaned_data.get("reference_high")
        notes = (cleaned_data.get("notes") or "").strip()

        if not any(
            [
                marker_name,
                value is not None,
                unit,
                reference_low is not None,
                reference_high is not None,
                notes,
            ]
        ):
            continue

        rows.append(
            {
                "marker_name": marker_name,
                "value": value,
                "unit": unit,
                "reference_low": reference_low,
                "reference_high": reference_high,
                "notes": notes,
                "display_order": index,
            }
        )
    return rows


def build_bloodwork_entries(user):
    entries = list(
        BloodworkEntry.objects.filter(user=user).prefetch_related(
            "measurements",
            Prefetch(
                "related_intakes",
                queryset=BloodworkRelatedIntake.objects.select_related("intake_log__compound").order_by(
                    "-intake_log__taken_at",
                    "-created_at",
                ),
            ),
        )
    )

    # For active-compound correlation: query all intake logs within a 7-day
    # lookback from the earliest collection date, prefetching effect windows.
    active_logs = []
    if entries:
        earliest = min(e.collected_at for e in entries)
        lookback_start = earliest - timedelta(days=7)
        active_logs = list(
            IntakeLog.objects.filter(user=user, taken_at__gte=lookback_start)
            .select_related("compound")
            .prefetch_related("compound__effect_windows")
        )

    marker_trend_data: dict = defaultdict(list)

    for entry in entries:
        related_compound_names = []
        related_log_rows = []
        seen_compound_ids = set()

        for relation in entry.related_intakes.all():
            intake_log = relation.intake_log
            related_log_rows.append(intake_log)
            if intake_log.compound_id in seen_compound_ids:
                continue
            seen_compound_ids.add(intake_log.compound_id)
            related_compound_names.append(intake_log.compound.name)

        entry.related_compound_names = related_compound_names
        entry.related_log_rows = related_log_rows

        # Compute which intake logs were pharmacologically active at collection time
        active_at_collection = []
        for intake in active_logs:
            duration_minutes = None
            for ew in intake.compound.effect_windows.all():
                if ew.duration_minutes and (duration_minutes is None or ew.duration_minutes > duration_minutes):
                    duration_minutes = ew.duration_minutes
            if duration_minutes is None:
                duration_minutes = 24 * 60  # 24h fallback for compounds with no window data
            window_end = intake.taken_at + timedelta(minutes=duration_minutes)
            if intake.taken_at <= entry.collected_at <= window_end:
                active_at_collection.append(intake)
        entry.active_compounds = active_at_collection

        # Accumulate marker trend data for charts
        date_str = timezone.localtime(entry.collected_at).strftime("%Y-%m-%d")
        for m in entry.measurements.all():
            marker_trend_data[m.marker_name].append({
                "date": date_str,
                "value": float(m.value),
                "ref_low": float(m.reference_low) if m.reference_low is not None else None,
                "ref_high": float(m.reference_high) if m.reference_high is not None else None,
            })

    # Sort each marker's trend chronologically for Chart.js
    for key in marker_trend_data:
        marker_trend_data[key].sort(key=lambda x: x["date"])

    return entries, dict(marker_trend_data)


@login_required
def bloodwork_dashboard(request):
    measurement_error = None

    if request.method == "POST":
        entry_form = BloodworkEntryForm(request.POST, user=request.user)
        measurement_formset = BloodworkMeasurementFormSet(request.POST, prefix="measurements")

        if entry_form.is_valid() and measurement_formset.is_valid():
            measurement_rows = _measurement_rows_from_formset(measurement_formset)
            if not measurement_rows:
                measurement_error = "Add at least one blood marker result before saving the panel."
            else:
                with transaction.atomic():
                    entry = entry_form.save(commit=False)
                    entry.user = request.user
                    entry.save()

                    related_logs = entry_form.cleaned_data.get("related_intake_logs")
                    if related_logs:
                        BloodworkRelatedIntake.objects.bulk_create(
                            [
                                BloodworkRelatedIntake(entry=entry, intake_log=intake_log)
                                for intake_log in related_logs
                            ]
                        )

                    BloodworkMeasurement.objects.bulk_create(
                        [
                            BloodworkMeasurement(entry=entry, **row)
                            for row in measurement_rows
                        ]
                    )

                return redirect(f"{reverse('bloodwork_dashboard')}?created=1")
    else:
        entry_form = BloodworkEntryForm(
            user=request.user,
            initial={
                "collected_at": timezone.localtime().replace(second=0, microsecond=0).strftime(
                    "%Y-%m-%dT%H:%M"
                )
            },
        )
        measurement_formset = BloodworkMeasurementFormSet(prefix="measurements")

    entries, marker_trend_data = build_bloodwork_entries(request.user)
    context = {
        "entry_form": entry_form,
        "measurement_formset": measurement_formset,
        "measurement_error": measurement_error,
        "entries": entries,
        "marker_trend_data": marker_trend_data,
        "panel_presets": COMMON_BIOMARKERS,
        "all_markers": _ALL_MARKERS_FLAT,
        "created": request.GET.get("created") == "1",
        "deleted": request.GET.get("deleted") == "1",
        "updated": request.GET.get("updated") == "1",
    }
    return render(request, "logs/bloodwork_dashboard.html", context)


@login_required
def bloodwork_edit(request, pk):
    entry = get_object_or_404(BloodworkEntry, pk=pk, user=request.user)
    measurement_error = None

    if request.method == "POST":
        entry_form = BloodworkEntryForm(request.POST, instance=entry, user=request.user)
        measurement_formset = BloodworkMeasurementFormSet(request.POST, prefix="measurements")

        if entry_form.is_valid() and measurement_formset.is_valid():
            measurement_rows = _measurement_rows_from_formset(measurement_formset)
            if not measurement_rows:
                measurement_error = "Add at least one blood marker result before saving the panel."
            else:
                with transaction.atomic():
                    updated_entry = entry_form.save(commit=False)
                    updated_entry.user = request.user
                    updated_entry.save()

                    updated_entry.measurements.all().delete()
                    BloodworkMeasurement.objects.bulk_create(
                        [BloodworkMeasurement(entry=updated_entry, **row) for row in measurement_rows]
                    )

                    BloodworkRelatedIntake.objects.filter(entry=updated_entry).delete()
                    related_logs = entry_form.cleaned_data.get("related_intake_logs")
                    if related_logs:
                        BloodworkRelatedIntake.objects.bulk_create(
                            [BloodworkRelatedIntake(entry=updated_entry, intake_log=il) for il in related_logs]
                        )

                return redirect(f"{reverse('bloodwork_dashboard')}?updated=1")
    else:
        entry_form = BloodworkEntryForm(
            instance=entry,
            user=request.user,
            initial={
                "collected_at": timezone.localtime(entry.collected_at).strftime("%Y-%m-%dT%H:%M"),
                "related_intake_logs": list(entry.related_intake_logs.values_list("id", flat=True)),
            },
        )
        initial_measurements = [
            {
                "marker_name": m.marker_name,
                "value": m.value,
                "unit": m.unit,
                "reference_low": m.reference_low,
                "reference_high": m.reference_high,
                "notes": m.notes,
            }
            for m in entry.measurements.all()
        ]
        measurement_formset = BloodworkMeasurementFormSet(prefix="measurements", initial=initial_measurements)

    context = {
        "entry": entry,
        "entry_form": entry_form,
        "measurement_formset": measurement_formset,
        "measurement_error": measurement_error,
        "all_markers": _ALL_MARKERS_FLAT,
        "panel_presets": COMMON_BIOMARKERS,
    }
    return render(request, "logs/bloodwork_edit.html", context)


@login_required
@require_POST
def bloodwork_delete(request, pk):
    entry = get_object_or_404(BloodworkEntry, pk=pk, user=request.user)
    entry.delete()
    return redirect(f"{reverse('bloodwork_dashboard')}?deleted=1")


@login_required
def bloodwork_print(request, pk):
    entry = get_object_or_404(BloodworkEntry, pk=pk, user=request.user)
    measurements = list(entry.measurements.all())
    for m in measurements:
        if m.reference_low is not None and m.reference_high is not None:
            if m.value < m.reference_low or m.value > m.reference_high:
                m.range_status = "out"
            else:
                m.range_status = "in"
        else:
            m.range_status = None

    related_intakes = list(
        BloodworkRelatedIntake.objects.filter(entry=entry)
        .select_related("intake_log__compound")
        .order_by("-intake_log__taken_at")
    )
    return render(request, "logs/bloodwork_print.html", {
        "entry": entry,
        "measurements": measurements,
        "related_intakes": related_intakes,
    })


@login_required
def analytics_dashboard(request):
    return render(request, "logs/analytics_dashboard.html", build_analytics_dashboard_context(request.user))


@staff_member_required
def ip_analytics_dashboard(request):
    new_ip_cutoff = timezone.now() - timedelta(hours=24)
    stale_cutoff = timezone.now() - timedelta(hours=max(1, int(getattr(settings, "ABUSEIPDB_REFRESH_HOURS", 24))))
    refresh_summary = None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        try:
            refresh_limit = int(request.POST.get("limit", "25"))
        except ValueError:
            refresh_limit = 25
        refresh_limit = max(1, min(250, refresh_limit))

        candidates = RequestIPProfile.objects.none()
        if action == "refresh_pending":
            candidates = RequestIPProfile.objects.filter(abuse_checked_at__isnull=True).order_by("-last_seen_at")[:refresh_limit]
        elif action == "refresh_stale":
            candidates = RequestIPProfile.objects.filter(
                abuse_checked_at__isnull=False,
                abuse_checked_at__lt=stale_cutoff,
            ).order_by("-abuse_checked_at")[:refresh_limit]

        refreshed_count = 0
        failed_count = 0
        attempted = 0
        for profile in candidates:
            attempted += 1
            updated = refresh_abuseipdb_profile(profile, force=True)
            if updated.abuse_check_error:
                failed_count += 1
            else:
                refreshed_count += 1

        refresh_summary = {
            "action": action,
            "attempted": attempted,
            "refreshed": refreshed_count,
            "failed": failed_count,
        }

    profile_qs = RequestIPProfile.objects.all()
    totals = profile_qs.aggregate(
        total_requests=Sum("total_requests"),
        total_errors=Sum("error_requests"),
    )

    threshold = int(getattr(settings, "ABUSE_THROTTLE_CONFIDENCE_THRESHOLD", 50))
    total_ips = profile_qs.count()
    new_ips_24h = profile_qs.filter(first_seen_at__gte=new_ip_cutoff).count()
    throttled_ips = profile_qs.filter(is_throttle_active=True).count()
    high_confidence_ips = profile_qs.filter(abuse_confidence_score__gt=threshold).count()

    ip_rows = list(profile_qs.order_by("-last_seen_at")[:200])
    for row in ip_rows:
        row.is_new = bool(row.first_seen_at and row.first_seen_at >= new_ip_cutoff)

    usage_type_rows = list(
        profile_qs.exclude(abuse_usage_type="")
        .values("abuse_usage_type")
        .annotate(ip_count=Count("id"), request_count=Sum("total_requests"))
        .order_by("-request_count", "-ip_count")[:20]
    )

    country_rows = list(
        profile_qs.exclude(abuse_country_code="")
        .values("abuse_country_code", "abuse_country_name")
        .annotate(ip_count=Count("id"), request_count=Sum("total_requests"))
        .order_by("-request_count", "-ip_count")
    )
    country_map_rows = [
        {
            "country_code": row["abuse_country_code"],
            "country_name": row["abuse_country_name"] or row["abuse_country_code"],
            "ip_count": row["ip_count"] or 0,
            "request_count": row["request_count"] or 0,
        }
        for row in country_rows
        if row["abuse_country_code"]
    ]

    top_path_rows = list(
        RequestIPPathStat.objects.values("path", "method")
        .annotate(request_count=Sum("request_count"), ip_count=Count("ip_profile", distinct=True))
        .order_by("-request_count")[:30]
    )

    context = {
        "total_ips": total_ips,
        "new_ips_24h": new_ips_24h,
        "throttled_ips": throttled_ips,
        "high_confidence_ips": high_confidence_ips,
        "total_requests": totals["total_requests"] or 0,
        "total_errors": totals["total_errors"] or 0,
        "error_rate_percent": (
            round(((totals["total_errors"] or 0) / max(1, totals["total_requests"] or 0)) * 100, 2)
            if totals["total_requests"]
            else 0
        ),
        "confidence_threshold": threshold,
        "ip_rows": ip_rows,
        "usage_type_rows": usage_type_rows,
        "country_rows": country_rows,
        "country_map_rows_json": json.dumps(country_map_rows),
        "top_path_rows": top_path_rows,
        "refresh_summary": refresh_summary,
        "abuse_auto_enrich": bool(getattr(settings, "ABUSEIPDB_AUTO_ENRICH_NEW_IPS", True)),
    }
    return render(request, "logs/ip_analytics_dashboard.html", context)


# REST Framework ViewSets
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
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
