import json
import csv
import hashlib
import math
import os
import re
import tempfile
from io import StringIO
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from urllib.parse import quote
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.db.models import Q, Count
from django.core.management import call_command
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import (
    Compound,
    CompoundADMETPrediction,
    CompoundMolPropPrediction,
    CompoundSafetyScreening,
    CompoundRating,
    CompoundCategories,
    CompoundMechanismOfAction,
    Target,
    EffectWindow,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    CompoundSteroidRating,
)
from .forms import CompoundForm, MechanismOfActionForm, CategoryForm, TargetForm
from .enrichment import enrich_compound
from .interaction_engine import canonicalize_mechanism

try:
    import requests
except Exception:  # pragma: no cover - dependency is expected in runtime image
    requests = None


def _push_recent_compound(request, compound):
    recent = request.session.get("recent_compounds", [])
    if not isinstance(recent, list):
        recent = []
    recent = [row for row in recent if row.get("slug") != compound.slug]
    recent.insert(0, {"slug": compound.slug, "name": compound.name})
    request.session["recent_compounds"] = recent[:8]


def _prediction_map(prediction_obj):
    if prediction_obj is None:
        return {}
    payload = getattr(prediction_obj, "predictions", None)
    if isinstance(payload, dict):
        return payload or {}
    return {}


def _coerce_prediction_number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    if isinstance(value, dict):
        for key in ("value", "prediction", "score"):
            if key in value:
                return _coerce_prediction_number(value.get(key))
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "positive"}:
            return 1.0
        if v in {"false", "no", "negative"}:
            return 0.0
        try:
            n = float(value)
        except ValueError:
            return None
        return n if math.isfinite(n) else None
    return None


def _merge_prediction_maps(
    admet_predictions: dict,
    molprop_predictions: dict,
) -> tuple[dict, dict]:
    """
    Merge two prediction maps for display.

    For shared numeric endpoints, output the arithmetic mean.
    For non-shared or non-numeric endpoints, keep the available value.
    """
    merged = {}
    sources = {}
    all_keys = set(admet_predictions.keys()) | set(molprop_predictions.keys())
    for key in all_keys:
        has_a = key in admet_predictions
        has_m = key in molprop_predictions
        a_raw = admet_predictions.get(key)
        m_raw = molprop_predictions.get(key)
        a_num = _coerce_prediction_number(a_raw) if has_a else None
        m_num = _coerce_prediction_number(m_raw) if has_m else None

        if a_num is not None and m_num is not None:
            merged[key] = (a_num + m_num) / 2.0
            sources[key] = "Averaged"
            continue

        if has_a and has_m:
            # Shared endpoint but non-numeric payloads: keep the primary cached value.
            merged[key] = a_raw if a_raw is not None else m_raw
            sources[key] = "Merged"
        elif has_a:
            merged[key] = a_raw
            sources[key] = "Single-source"
        elif has_m:
            merged[key] = m_raw
            sources[key] = "Single-source"
    return merged, sources


def _build_compound_depth1_graph(compound):
    """
    Build a compact, non-interactive depth-1 graph payload for compound detail.

    Depth-1 includes direct neighbors of the anchor compound:
    - Target neighbors from CompoundTargetInteraction
    - Compound neighbors from CompoundToCompoundTargetInteraction
    - Shared-target target neighbors from compound-compound interactions
    """
    neighbor_map = {}
    anchor_node_id = f"compound:{compound.id}"

    def _ensure_neighbor(node_id, node_type, label, note=""):
        row = neighbor_map.get(node_id)
        if row is None:
            row = {
                "id": node_id,
                "node_type": node_type,
                "label": label or "Unknown",
                "note": note or "",
                "relations": [],
            }
            neighbor_map[node_id] = row
            return row
        if note and not row.get("note"):
            row["note"] = note
        return row

    def _add_relation(row, relation_label):
        label = (relation_label or "").strip()
        if not label:
            return
        if label in row["relations"]:
            return
        row["relations"].append(label)

    cti_rows = (
        CompoundTargetInteraction.objects.filter(compound_id=compound.id)
        .select_related("target")
        .order_by("target__name", "mechanism")[:80]
    )
    for cti in cti_rows:
        target_node_id = f"target:{cti.target_id}"
        neighbor = _ensure_neighbor(
            target_node_id,
            "target",
            cti.target.name,
            note=(cti.target.gene_name or "").strip(),
        )
        affinity_label = cti.get_affinity_level_display()
        affinity_suffix = "" if cti.affinity_level == "unknown" else f" ({affinity_label})"
        _add_relation(neighbor, f"{cti.get_mechanism_display()}{affinity_suffix}")

    cci_rows = (
        CompoundToCompoundTargetInteraction.objects.filter(
            Q(compound_a_id=compound.id) | Q(compound_b_id=compound.id)
        )
        .select_related("compound_a", "compound_b", "target")
        .order_by("target__name", "compound_a__name", "compound_b__name")[:80]
    )
    for cci in cci_rows:
        other_compound = cci.compound_b if cci.compound_a_id == compound.id else cci.compound_a
        other_node_id = f"compound:{other_compound.id}"
        compound_neighbor = _ensure_neighbor(
            other_node_id,
            "compound",
            other_compound.name,
            note=(other_compound.aliases or "").strip(),
        )
        _add_relation(compound_neighbor, f"{cci.get_interaction_type_display()} via {cci.target.name}")

        target_node_id = f"target:{cci.target_id}"
        target_neighbor = _ensure_neighbor(
            target_node_id,
            "target",
            cci.target.name,
            note=(cci.target.gene_name or "").strip(),
        )
        _add_relation(target_neighbor, "shared target")

    neighbors = sorted(
        neighbor_map.values(),
        key=lambda row: (0 if row["node_type"] == "target" else 1, row["label"].lower()),
    )
    if not neighbors:
        return {
            "nodes": [
                {
                    "id": anchor_node_id,
                    "node_type": "compound",
                    "label": compound.name,
                    "note": (compound.aliases or "").strip(),
                    "x": 0.0,
                    "y": 0.0,
                    "text_y": 30.0,
                    "is_anchor": True,
                }
            ],
            "edges": [],
            "radius": 0,
        }

    neighbor_count = len(neighbors)
    radius = max(175, min(320, 145 + neighbor_count * 7))

    nodes = [
        {
            "id": anchor_node_id,
            "node_type": "compound",
            "label": compound.name,
            "note": (compound.aliases or "").strip(),
            "x": 0.0,
            "y": 0.0,
            "text_y": 30.0,
            "is_anchor": True,
        }
    ]
    edges = []

    for idx, neighbor in enumerate(neighbors):
        angle = (-math.pi / 2.0) + ((2.0 * math.pi * idx) / max(neighbor_count, 1))
        nx = round(math.cos(angle) * radius, 2)
        ny = round(math.sin(angle) * radius, 2)
        relation_labels = neighbor.get("relations", [])
        relation_label = " • ".join(relation_labels[:2]) if relation_labels else "related"

        nodes.append(
            {
                "id": neighbor["id"],
                "node_type": neighbor["node_type"],
                "label": neighbor["label"],
                "note": neighbor.get("note", ""),
                "x": nx,
                "y": ny,
                "text_y": round(ny + 30.0, 2),
                "is_anchor": False,
            }
        )
        edges.append(
            {
                "source_id": anchor_node_id,
                "target_id": neighbor["id"],
                "source_x": 0.0,
                "source_y": 0.0,
                "target_x": nx,
                "target_y": ny,
                "mid_x": round(nx / 2.0, 2),
                "mid_y": round(ny / 2.0, 2),
                "label": relation_label,
            }
        )

    return {"nodes": nodes, "edges": edges, "radius": radius}


def _auto_enrich_compound_on_access(compound: Compound) -> None:
    try:
        enrich_compound(compound)
    except Exception:
        pass

    if CompoundTargetInteraction.objects.filter(compound=compound).exists():
        return

    try:
        _import_missing_mechanisms_for_compound(compound)
    except Exception:
        return


def compound_detail(request, slug):
    compound = get_object_or_404(Compound.objects.select_related('steroid_ratings'), slug=slug)
    _auto_enrich_compound_on_access(compound)
    try:
        steroid_ratings = compound.steroid_ratings
    except CompoundSteroidRating.DoesNotExist:
        steroid_ratings = None
    
    # Increment view count
    compound.increment_views()
    _push_recent_compound(request, compound)
    
    #safety_report = CompoundSafetyScreening.objects.filter(compound=compound).order_by('-created_by').first()
    #safety_report = compound.compoundsafetyscreening_set.all()
    safety_report = getattr(compound, 'safety_report', None)
    compound_has_effect_curves = EffectWindow.objects.filter(compound=compound).exists()

    compound_rating = CompoundRating.objects.filter(compound=compound).all()
    avg_rating = compound_rating.aggregate(models.Avg('score'))['score__avg']

    user_rating = None
    if request.user.is_authenticated:
        try:
            user_rating = CompoundRating.objects.get(compound=compound, user=request.user).score
        except CompoundRating.DoesNotExist:
            pass
    
    # Get research snippets for this compound
    try:
        from research.models import ResearchSnippet, SnippetReview
        
        # Filter snippets based on user permissions
        snippets = ResearchSnippet.objects.filter(compound=compound).select_related('created_by').prefetch_related('reviews')
        
        if request.user.is_authenticated:
            if not request.user.is_staff:
                # Regular users see public snippets + their own drafts
                snippets = snippets.filter(
                    Q(visibility='public') |
                    Q(created_by=request.user, visibility='draft')
                )
        else:
            # Anonymous users only see public snippets
            snippets = snippets.filter(visibility='public')
        
        # Annotate with review counts and user's review status
        snippets = snippets.annotate(
            positive_reviews=Count('reviews', filter=Q(reviews__vote_type='validate')),
            negative_reviews=Count('reviews', filter=Q(reviews__vote_type='reject'))
        ).order_by('-created_at')
        
        # Check if user has reviewed each snippet
        user_reviews = {}
        if request.user.is_authenticated:
            user_review_qs = SnippetReview.objects.filter(
                snippet__in=snippets,
                reviewer=request.user
            ).values('snippet_id', 'vote_type')
            user_reviews = {r['snippet_id']: r['vote_type'] for r in user_review_qs}
            
    except ImportError:
        # Research app not installed
        snippets = []
        user_reviews = {}

    # Get mechanisms ordered by affinity from CompoundTargetInteraction
    # Priority order: very_high > high > medium > low > very_low > unknown
    affinity_order = {
        'very_high': 1,
        'high': 2, 
        'medium': 3,
        'low': 4,
        'very_low': 5,
        'unknown': 6,
    }
    
    # Get target interactions with affinity data
    target_interactions = compound.target_interactions.select_related('target').all()
    
    # Sort by affinity priority (lower number = higher priority)
    target_interactions = sorted(target_interactions, 
                               key=lambda x: affinity_order.get(x.affinity_level, 6))

    # ADMET-AI cached predictions
    try:
        from .admet_ai import is_admet_ai_available

        admet_ai_available = is_admet_ai_available()
    except Exception:
        admet_ai_available = False

    # MolProp cached predictions
    molprop_unavailable_reason = ""
    try:
        from .molprop import is_molprop_available, get_molprop_unavailable_reason

        molprop_available = is_molprop_available()
        molprop_unavailable_reason = get_molprop_unavailable_reason()
    except Exception:
        molprop_available = False
        molprop_unavailable_reason = ""

    admet_prediction = getattr(compound, "admet_ai_prediction", None)
    molprop_prediction = getattr(compound, "molprop_prediction", None)
    admet_predictions = _prediction_map(admet_prediction)
    molprop_predictions = _prediction_map(molprop_prediction)
    merged_predictions, merged_prediction_sources = _merge_prediction_maps(
        admet_predictions,
        molprop_predictions,
    )
    smiles_hash = (
        hashlib.sha256(compound.smiles.encode("utf-8")).hexdigest()
        if compound.smiles
        else ""
    )
    admet_prediction_is_stale = bool(
        admet_prediction and smiles_hash and admet_prediction.smiles_sha256 != smiles_hash
    )
    molprop_prediction_is_stale = bool(
        molprop_prediction and smiles_hash and molprop_prediction.smiles_sha256 != smiles_hash
    )
    admet_ai_mechanisms = []
    admet_ai_mechanism_context = {'mechanisms': [], 'groups': {}, 'summary': {}, 'references': []}
    try:
        from .admet_mechanisms import build_predicted_mechanism_context

        primary_predictions = {}
        secondary_predictions = {}
        secondary_label = "MolProp"
        if admet_predictions:
            primary_predictions = dict(merged_predictions)
            secondary_predictions = dict(molprop_predictions)
            secondary_label = "MolProp"
        elif molprop_predictions:
            primary_predictions = dict(molprop_predictions)
            secondary_predictions = {}
            secondary_label = "ADMET-AI"

        if primary_predictions:
            admet_ai_mechanism_context = build_predicted_mechanism_context(
                primary_predictions,
                target_interactions=target_interactions,
                secondary_predictions=secondary_predictions,
                secondary_label=secondary_label,
            )
            admet_ai_mechanisms = admet_ai_mechanism_context.get('mechanisms', [])
    except Exception:
        admet_ai_mechanisms = []
        admet_ai_mechanism_context = {'mechanisms': [], 'groups': {}, 'summary': {}, 'references': []}
    admet_ai_autoload = bool(
        request.user.is_authenticated
        and admet_ai_available
        and compound.smiles
        and (admet_prediction is None or admet_prediction_is_stale)
    )
    molprop_autoload = bool(
        request.user.is_authenticated
        and molprop_available
        and compound.smiles
        and (molprop_prediction is None or molprop_prediction_is_stale)
    )

    context = {
        'compound': compound,
        'steroid_ratings': steroid_ratings,
        'compound_has_effect_curves': compound_has_effect_curves,
        'compound_depth1_graph': _build_compound_depth1_graph(compound),
        'safety_report': safety_report,
        'avg_rating': round(avg_rating, 2) if avg_rating else None,
        'user_rating': user_rating,
        'research_snippets': snippets,
        'user_reviews': user_reviews,
        'all_categories': CompoundCategories.objects.all(),
        'target_interactions': target_interactions,
        'admet_ai_available': admet_ai_available,
        'admet_ai_prediction': admet_prediction,
        'admet_ai_prediction_is_stale': admet_prediction_is_stale,
        'admet_panel_predictions': merged_predictions,
        'admet_panel_prediction_sources': merged_prediction_sources,
        'admet_panel_source_payload': {
            'admet_predictions': admet_predictions,
            'molprop_predictions': molprop_predictions,
            'molprop_uncertainty': getattr(molprop_prediction, "uncertainty", {}) if molprop_prediction else {},
        },
        'admet_ai_refresh_url': reverse('compound_admet_ai_refresh', kwargs={'slug': compound.slug}),
        'admet_ai_status': request.GET.get('admet', ''),
        'admet_ai_autoload': admet_ai_autoload,
        'molprop_available': molprop_available,
        'molprop_prediction': molprop_prediction,
        'molprop_prediction_is_stale': molprop_prediction_is_stale,
        'molprop_refresh_url': reverse('compound_molprop_refresh', kwargs={'slug': compound.slug}),
        'molprop_status': request.GET.get('molprop', ''),
        'molprop_autoload': molprop_autoload,
        'molprop_unavailable_reason': molprop_unavailable_reason,
        'admet_ai_mechanisms': admet_ai_mechanisms,
        'admet_ai_mechanism_context': admet_ai_mechanism_context,
        'research_import_status': request.GET.get('research_import', ''),
        'mechanism_import_status': request.GET.get('mechanism_import', ''),
        'mechanism_import_count': request.GET.get('mechanism_import_count', ''),
        'mechanism_import_source': request.GET.get('mechanism_import_source', ''),
    }

    return render(request, 'compounds/compound_detail.html', context)


def compound_details(request, slug):
    """Enhanced compound details view with view tracking"""
    return compound_detail(request, slug)


def target_detail(request, target_id):
    target = get_object_or_404(Target, id=target_id)
    interactions = (
        CompoundTargetInteraction.objects
        .filter(target=target)
        .select_related('compound')
        .order_by('compound__name', 'mechanism')
    )

    compounds_by_relationship = {}
    for interaction in interactions:
        compound_id = interaction.compound_id
        row = compounds_by_relationship.setdefault(
            compound_id,
            {
                'compound': interaction.compound,
                'relationship_types': set(),
            },
        )
        if interaction.mechanism:
            row['relationship_types'].add(interaction.get_mechanism_display())

    related_compounds = sorted(
        [
            {
                'compound': row['compound'],
                'relationship_types': sorted(row['relationship_types']) or ['Unknown'],
            }
            for row in compounds_by_relationship.values()
        ],
        key=lambda row: row['compound'].name.lower(),
    )

    return render(
        request,
        'compounds/target_detail.html',
        {
            'target': target,
            'related_compounds': related_compounds,
            'interaction_count': interactions.count(),
        },
    )


def is_staff_user(user):
    return user.is_authenticated and user.is_staff


def _append_query_params(url: str, params: dict) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None})
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


_MOA_INTERACTION_CHOICES = {
    key for key, _ in CompoundMechanismOfAction.INTERACTION_TYPES
}
_CTI_MECHANISM_CHOICES = {
    key for key, _ in CompoundTargetInteraction.MECHANISM_CHOICES
}


def _normalize_interaction(action_type: str = "", mechanism_text: str = "") -> str:
    canonical = canonicalize_mechanism(
        action_type=action_type,
        mechanism_of_action=mechanism_text,
    )
    if canonical in _MOA_INTERACTION_CHOICES:
        return canonical
    return "unknown"


def _existing_mechanism_keys(compound: Compound) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for row in compound.mechanism_of_action.all().select_related("target_name"):
        target_label = (
            (getattr(row.target_name, "name", "") or "").strip().lower() if row.target_name_id else ""
        )
        interaction = (row.target_interaction or "").strip().lower()
        if interaction:
            keys.add((target_label, interaction))
    return keys


def _fetch_chembl_mechanisms_for_compound(compound: Compound) -> list[dict]:
    from .management.commands.import_chembl_interactions import ChEMBLImporter

    importer = ChEMBLImporter(slow_mode=False)
    chembl_id = (compound.chembl_id or "").strip().upper()
    if not chembl_id:
        chembl_id = (importer.get_compound_by_name(compound.name) or "").strip().upper()
    if not chembl_id:
        return []

    mechanisms = importer.get_compound_mechanisms(chembl_id) or []
    rows: list[dict] = []
    for mech in mechanisms:
        mechanism_text = (mech.get("mechanism_of_action") or "").strip()
        action_type = (mech.get("action_type") or "").strip()
        if not mechanism_text and not action_type:
            continue
        target_name = ""
        target_type = ""
        target_chembl_id = (mech.get("target_chembl_id") or "").strip()
        if target_chembl_id:
            target_data = importer.get_target_details(target_chembl_id) or {}
            target_name = (target_data.get("pref_name") or target_data.get("target_name") or "").strip()
            target_type = (target_data.get("target_type") or "").strip().lower().replace(" ", "_")
        rows.append(
            {
                "source": "chembl",
                "target_name": target_name,
                "target_chembl_id": target_chembl_id,
                "target_type": target_type,
                "interaction": _normalize_interaction(action_type=action_type, mechanism_text=mechanism_text),
                "description": f"{mechanism_text or action_type} (ChEMBL)",
            }
        )
    return rows


def _iter_pubchem_section_text(section: dict) -> list[str]:
    out: list[str] = []
    info_rows = section.get("Information") or []
    for info in info_rows:
        value = info.get("Value") or {}
        strings = value.get("StringWithMarkup") or []
        for row in strings:
            text = (row.get("String") or "").strip()
            if text:
                out.append(text)
        plain = value.get("String")
        if isinstance(plain, str) and plain.strip():
            out.append(plain.strip())
    for child in (section.get("Section") or []):
        out.extend(_iter_pubchem_section_text(child))
    return out


def _fetch_pubchem_mechanisms_for_compound(compound: Compound) -> list[dict]:
    if requests is None:
        return []

    cid_value = (compound.pubchem_cid or "").strip()
    try:
        if not cid_value:
            safe_name = quote((compound.name or "").strip())
            if not safe_name:
                return []
            cid_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{safe_name}/cids/JSON"
            cid_resp = requests.get(cid_url, timeout=20)
            if cid_resp.status_code == 404:
                return []
            cid_resp.raise_for_status()
            cid_payload = cid_resp.json() if cid_resp.content else {}
            cids = (((cid_payload.get("IdentifierList") or {}).get("CID")) or [])[:1]
            if not cids:
                return []
            cid_value = str(cids[0]).strip()

        if not cid_value:
            return []

        view_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{quote(cid_value)}/JSON"
        view_resp = requests.get(view_url, timeout=20)
        if view_resp.status_code == 404:
            return []
        view_resp.raise_for_status()
        view_payload = view_resp.json() if view_resp.content else {}
    except Exception:
        # External API failures should not abort the full import flow.
        return []

    record = view_payload.get("Record") or {}
    sections = record.get("Section") or []

    entries: list[dict] = []
    for section in sections:
        heading = (section.get("TOCHeading") or "").strip().lower()
        if "mechanism of action" not in heading:
            continue
        for text in _iter_pubchem_section_text(section):
            cleaned = re.sub(r"\s+", " ", text).strip()
            if not cleaned:
                continue
            entries.append(
                {
                    "source": "pubchem",
                    "target_name": "",
                    "target_chembl_id": "",
                    "target_type": "other",
                    "interaction": _normalize_interaction(mechanism_text=cleaned),
                    "description": f"{cleaned} (PubChem)",
                }
            )
    return entries


def _fetch_zinc_mechanisms_for_compound(compound: Compound) -> list[dict]:
    # ZINC does not provide a stable public mechanism endpoint comparable to ChEMBL/PubChem.
    # Keep this probe lightweight and return no mechanisms when unavailable.
    if requests is None:
        return []
    safe_name = quote(compound.name.strip())
    probe_url = f"https://zinc.docking.org/substances/search/?q={safe_name}"
    resp = requests.get(probe_url, timeout=20)
    if resp.status_code != 200:
        return []
    return []


def _import_missing_mechanisms_for_compound(compound: Compound) -> dict:
    existing_keys = _existing_mechanism_keys(compound)
    existing_target_interactions = set(
        CompoundTargetInteraction.objects.filter(compound=compound).values_list("target_id", "mechanism")
    )
    imported = 0
    source_used = ""
    attempted_sources: list[str] = []

    source_fetchers = [
        ("chembl", _fetch_chembl_mechanisms_for_compound),
        ("zinc", _fetch_zinc_mechanisms_for_compound),
        ("pubchem", _fetch_pubchem_mechanisms_for_compound),
    ]

    for source_name, fetcher in source_fetchers:
        attempted_sources.append(source_name)
        try:
            rows = fetcher(compound) or []
        except Exception:
            continue
        if not rows:
            continue

        added_this_source = 0
        for row in rows:
            interaction = (row.get("interaction") or "unknown").strip().lower()
            cti_mechanism = interaction if interaction in _CTI_MECHANISM_CHOICES else "unknown"
            target_name_raw = (row.get("target_name") or "").strip()
            target_key = target_name_raw.lower()
            dedupe_key = (target_key, interaction)

            target_obj = None
            if target_name_raw:
                target_defaults = {
                    "target_type": (row.get("target_type") or "other")[:100] or "other",
                    "type": (row.get("target_type") or "other")[:100] or "other",
                }
                target_chembl_id = (row.get("target_chembl_id") or "").strip()
                if target_chembl_id:
                    target_defaults["chembl_id"] = target_chembl_id[:20]
                target_obj, _ = Target.objects.get_or_create(
                    name=target_name_raw[:255],
                    defaults=target_defaults,
                )

            if dedupe_key not in existing_keys:
                moa, _ = CompoundMechanismOfAction.objects.get_or_create(
                    target_name=target_obj,
                    target_type=(row.get("target_type") or "other")[:100] or "other",
                    target_interaction=interaction if interaction in _MOA_INTERACTION_CHOICES else "unknown",
                    description=(row.get("description") or "")[:1000],
                )
                compound.mechanism_of_action.add(moa)
                existing_keys.add(dedupe_key)
                imported += 1
                added_this_source += 1

            if not target_obj:
                continue

            cti_key = (target_obj.id, cti_mechanism)
            if cti_key in existing_target_interactions:
                continue

            CompoundTargetInteraction.objects.create(
                compound=compound,
                target=target_obj,
                mechanism=cti_mechanism,
                affinity_level="unknown",
                notes=(row.get("description") or "")[:1000],
                source=(row.get("source") or source_name).upper()[:100],
            )
            existing_target_interactions.add(cti_key)
            imported += 1
            added_this_source += 1

        if added_this_source > 0:
            source_used = source_name
            break

    return {
        "imported": imported,
        "source": source_used,
        "attempted": attempted_sources,
    }


def _fetch_pubchem_compound_properties(pubchem_cid: str) -> dict:
    if requests is None:
        return {}

    safe_cid = quote((pubchem_cid or "").strip())
    if not safe_cid:
        return {}

    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
        f"{safe_cid}/property/"
        "Title,CanonicalSMILES,SMILES,ConnectivitySMILES,IsomericSMILES,"
        "InChI,InChIKey,IUPACName,MolecularFormula,MolecularWeight/JSON"
    )
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    payload = response.json() if response.content else {}
    properties = ((payload.get("PropertyTable") or {}).get("Properties")) or []
    if not properties or not isinstance(properties[0], dict):
        return {}

    row = properties[0]
    smiles_value = (
        (row.get("CanonicalSMILES") or "")
        or (row.get("SMILES") or "")
        or (row.get("IsomericSMILES") or "")
        or (row.get("ConnectivitySMILES") or "")
    ).strip()
    return {
        "title": (row.get("Title") or "").strip(),
        "smiles": smiles_value,
        "inchi": (row.get("InChI") or "").strip(),
        "inchi_key": (row.get("InChIKey") or "").strip(),
        "iupac_name": (row.get("IUPACName") or "").strip(),
        "molecular_formula": (row.get("MolecularFormula") or "").strip(),
        "molecular_weight": str(row.get("MolecularWeight") or "").strip(),
    }


_CHEMBL_ID_RE = re.compile(r"^CHEMBL\d+$", flags=re.IGNORECASE)


def _fetch_pubchem_registry_ids(pubchem_cid: str) -> list[str]:
    if requests is None:
        return []

    cid = (pubchem_cid or "").strip()
    if not cid:
        return []

    safe_cid = quote(cid)
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{safe_cid}/xrefs/RegistryID/JSON"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception:
        return []

    info_rows = ((payload.get("InformationList") or {}).get("Information")) or []
    if not info_rows or not isinstance(info_rows[0], dict):
        return []

    registry_ids = info_rows[0].get("RegistryID") or []
    if not isinstance(registry_ids, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for raw in registry_ids:
        text = (str(raw) if raw is not None else "").strip()
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _fetch_pubchem_synonyms(pubchem_cid: str) -> list[str]:
    if requests is None:
        return []

    cid = (pubchem_cid or "").strip()
    if not cid:
        return []

    safe_cid = quote(cid)
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{safe_cid}/synonyms/JSON"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception:
        return []

    info_rows = ((payload.get("InformationList") or {}).get("Information")) or []
    if not info_rows or not isinstance(info_rows[0], dict):
        return []

    raw_synonyms = info_rows[0].get("Synonym") or []
    if not isinstance(raw_synonyms, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_synonyms:
        text = (str(raw) if raw is not None else "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _iter_pubchem_sections(sections: list[dict]) -> list[dict]:
    out: list[dict] = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        out.append(section)
        children = section.get("Section") or []
        if children:
            out.extend(_iter_pubchem_sections(children))
    return out


def _fetch_pubchem_summary(pubchem_cid: str) -> str:
    if requests is None:
        return ""

    cid = (pubchem_cid or "").strip()
    if not cid:
        return ""

    safe_cid = quote(cid)
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{safe_cid}/JSON"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception:
        return ""

    record = payload.get("Record") or {}
    sections = _iter_pubchem_sections(record.get("Section") or [])
    preferred: list[str] = []
    fallback: list[str] = []

    for section in sections:
        heading = (section.get("TOCHeading") or "").strip().lower()
        texts = [
            re.sub(r"\s+", " ", text).strip()
            for text in _iter_pubchem_section_text(section)
        ]
        texts = [text for text in texts if text]
        if not texts:
            continue
        first = texts[0]
        if heading in {"record description", "summary"}:
            return first
        if "description" in heading or "summary" in heading:
            preferred.append(first)
        elif "use" in heading or "drug" in heading:
            fallback.append(first)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return ""


def _normalize_summary_text(raw_value: str) -> str:
    return re.sub(r"\s+", " ", str(raw_value or "")).strip()


def _join_summary_sentences(parts: list[str]) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for raw_part in parts or []:
        text = _normalize_summary_text(raw_part)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if text[-1] not in '.!?':
            text = f"{text}."
        merged.append(text)
    return " ".join(merged)


def _join_alias_candidates(values: list[str], *, max_items: int = 6, max_length: int = 255) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        cleaned = normalize_compound_name(raw_value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        candidate = ", ".join(merged + [cleaned])
        if len(candidate) > max_length:
            break
        seen.add(key)
        merged.append(cleaned)
        if len(merged) >= max_items:
            break
    return ", ".join(merged)


def _build_pubchem_summary_fallback(pubchem_cid: str, payload: dict) -> str:
    cid = (pubchem_cid or "").strip()
    name = _normalize_summary_text(payload.get("title") or payload.get("iupac_name") or f"PubChem CID {cid}")
    formula = _normalize_summary_text(payload.get("molecular_formula"))
    weight = _normalize_summary_text(payload.get("molecular_weight"))
    iupac_name = _normalize_summary_text(payload.get("iupac_name"))

    parts: list[str] = []
    if name:
        intro = f"{name} is listed in PubChem"
        details: list[str] = []
        if formula:
            details.append(f"formula {formula}")
        if weight:
            details.append(f"molecular weight {weight} g/mol")
        if details:
            intro = f"{intro} with {' and '.join(details)}"
        parts.append(intro)
    if iupac_name and iupac_name.lower() != name.lower():
        parts.append(f"IUPAC name: {iupac_name}")
    return _join_summary_sentences(parts)


def _fetch_chembl_summary_snapshot(chembl_id: str) -> dict:
    if requests is None:
        return {}

    chembl_key = (chembl_id or "").strip().upper()
    if not _CHEMBL_ID_RE.fullmatch(chembl_key):
        return {}

    molecule_url = f"https://www.ebi.ac.uk/chembl/api/data/molecule/{quote(chembl_key)}.json"
    mechanism_url = (
        "https://www.ebi.ac.uk/chembl/api/data/mechanism.json?"
        f"molecule_chembl_id={quote(chembl_key)}&limit=5"
    )
    indication_url = (
        "https://www.ebi.ac.uk/chembl/api/data/drug_indication.json?"
        f"molecule_chembl_id={quote(chembl_key)}&limit=5"
    )
    headers = {"Accept": "application/json"}

    try:
        molecule_resp = requests.get(molecule_url, headers=headers, timeout=20)
        if molecule_resp.status_code == 404:
            return {}
        molecule_resp.raise_for_status()
        molecule_payload = molecule_resp.json() if molecule_resp.content else {}
    except Exception:
        return {}

    try:
        mechanism_resp = requests.get(mechanism_url, headers=headers, timeout=20)
        mechanism_resp.raise_for_status()
        mechanism_payload = mechanism_resp.json() if mechanism_resp.content else {}
    except Exception:
        mechanism_payload = {}

    try:
        indication_resp = requests.get(indication_url, headers=headers, timeout=20)
        indication_resp.raise_for_status()
        indication_payload = indication_resp.json() if indication_resp.content else {}
    except Exception:
        indication_payload = {}

    molecule_properties = molecule_payload.get("molecule_properties") or {}
    molecule_structures = molecule_payload.get("molecule_structures") or {}
    mechanisms = mechanism_payload.get("mechanisms") or []
    indications = indication_payload.get("drug_indications") or []

    mechanism_bits: list[str] = []
    for row in mechanisms:
        if not isinstance(row, dict):
            continue
        mechanism_text = _normalize_summary_text(row.get("mechanism_of_action"))
        action_type = _normalize_summary_text(row.get("action_type"))
        target_name = _normalize_summary_text(row.get("target_pref_name") or row.get("target_name"))
        descriptor = mechanism_text or action_type
        if target_name and descriptor:
            descriptor = f"{descriptor} at {target_name}"
        elif target_name:
            descriptor = f"targeting {target_name}"
        if descriptor:
            mechanism_bits.append(descriptor)

    indication_bits: list[str] = []
    for row in indications:
        if not isinstance(row, dict):
            continue
        label = _normalize_summary_text(row.get("mesh_heading") or row.get("efo_term") or row.get("indication_refs"))
        if label:
            indication_bits.append(label)

    synonym_bits: list[str] = []
    for row in (molecule_payload.get("molecule_synonyms") or []):
        if not isinstance(row, dict):
            continue
        synonym = _normalize_summary_text(row.get("molecule_synonym"))
        if synonym:
            synonym_bits.append(synonym)

    name = _normalize_summary_text(molecule_payload.get("pref_name")) or chembl_key
    molecule_type = _normalize_summary_text(molecule_payload.get("molecule_type"))
    max_phase_raw = molecule_payload.get("max_phase")
    try:
        max_phase = int(max_phase_raw)
    except (TypeError, ValueError):
        max_phase = 0
    first_approval = _normalize_summary_text(molecule_payload.get("first_approval"))

    summary_parts: list[str] = []
    intro = f"{name} is listed in ChEMBL"
    if molecule_type:
        intro = f"{intro} as a {molecule_type.lower()}"
    summary_parts.append(intro)

    if bool(molecule_payload.get("therapeutic_flag")):
        summary_parts.append("ChEMBL flags it as a therapeutic molecule")
    if max_phase > 0:
        summary_parts.append(f"Recorded max clinical phase: {max_phase}")
    if first_approval:
        summary_parts.append(f"First approval year: {first_approval}")
    if mechanism_bits:
        summary_parts.append(f"Reported mechanism notes: {'; '.join(mechanism_bits[:3])}")
    if indication_bits:
        summary_parts.append(f"Indications include {'; '.join(indication_bits[:3])}")

    return {
        "name": name,
        "description": _join_summary_sentences(summary_parts),
        "chembl_id": chembl_key,
        "smiles": _normalize_summary_text(molecule_structures.get("canonical_smiles")),
        "inchi": _normalize_summary_text(molecule_structures.get("standard_inchi")),
        "inchi_key": _normalize_summary_text(molecule_structures.get("standard_inchi_key")),
        "iupac_name": name,
        "molecular_formula": _normalize_summary_text(molecule_properties.get("full_molformula")),
        "molecular_weight": _normalize_summary_text(molecule_properties.get("full_mwt")),
        "mechanism_of_action_summary": _join_summary_sentences([f"Reported mechanism notes: {'; '.join(mechanism_bits[:3])}"]) if mechanism_bits else "",
        "aliases": _join_alias_candidates(synonym_bits),
    }


def _fetch_wikipedia_summary_snapshot(query: str) -> dict:
    if requests is None:
        return {}

    lookup = _normalize_summary_text(query)
    if not lookup:
        return {}

    headers = {
        "Accept": "application/json",
        "User-Agent": "Neurobin/1.0 (compound summary importer)",
    }

    try:
        search_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": lookup,
                "format": "json",
                "utf8": 1,
                "srlimit": 1,
            },
            headers=headers,
            timeout=20,
        )
        search_resp.raise_for_status()
        search_payload = search_resp.json() if search_resp.content else {}
    except Exception:
        return {}

    search_rows = ((search_payload.get("query") or {}).get("search")) or []
    title = ""
    if search_rows and isinstance(search_rows[0], dict):
        title = _normalize_summary_text(search_rows[0].get("title"))
    if not title:
        title = lookup

    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
    try:
        summary_resp = requests.get(summary_url, headers=headers, timeout=20)
        if summary_resp.status_code == 404:
            return {}
        summary_resp.raise_for_status()
        summary_payload = summary_resp.json() if summary_resp.content else {}
    except Exception:
        return {}

    description = _normalize_summary_text(summary_payload.get("extract"))
    if not description:
        return {}

    page_url = _normalize_summary_text(
        (((summary_payload.get("content_urls") or {}).get("desktop") or {}).get("page"))
    )
    resolved_title = _normalize_summary_text(summary_payload.get("title")) or title
    return {
        "name": resolved_title,
        "description": description,
        "wikipedia_url": page_url,
    }


def _fetch_best_external_summary(*, pubchem_cid: str = "", chembl_id: str = "", name: str = "") -> str:
    cid = (pubchem_cid or "").strip()
    chembl_key = (chembl_id or "").strip().upper()
    fallback_name = _normalize_summary_text(name)

    if cid:
        summary = _fetch_pubchem_summary(cid)
        if summary:
            return summary

    if chembl_key:
        snapshot = _fetch_chembl_summary_snapshot(chembl_key)
        description = _normalize_summary_text(snapshot.get("description"))
        if description:
            return description

    if fallback_name:
        snapshot = _fetch_wikipedia_summary_snapshot(fallback_name)
        description = _normalize_summary_text(snapshot.get("description"))
        if description:
            return description

    return ""


def _prepare_summary_import_initial(source: str, query: str) -> tuple[dict, str]:
    source_key = (source or "").strip().lower()
    lookup = _normalize_summary_text(query)

    if source_key == "pubchem":
        if not lookup:
            return {}, "Enter a PubChem CID to import a summary."
        if not lookup.isdigit():
            return {}, 'PubChem CID must be numeric (example: 2244).'

        payload = _fetch_pubchem_compound_properties(lookup)
        if not payload:
            return {}, f"No PubChem record found for CID {lookup}."

        description = _fetch_pubchem_summary(lookup) or _build_pubchem_summary_fallback(lookup, payload)
        if not description:
            return {}, f"No importable summary was found for CID {lookup}."

        inchi_key = _normalize_summary_text(payload.get("inchi_key"))
        return {
            "name": _normalize_summary_text(payload.get("title") or payload.get("iupac_name") or f"PubChem CID {lookup}"),
            "description": description,
            "pubchem_cid": lookup,
            "chembl_id": _resolve_pubchem_chembl_id(lookup, inchi_key),
            "smiles": _normalize_summary_text(payload.get("smiles")),
            "inchi": _normalize_summary_text(payload.get("inchi")),
            "inchi_key": inchi_key,
            "iupac_name": _normalize_summary_text(payload.get("iupac_name")),
            "molecular_formula": _normalize_summary_text(payload.get("molecular_formula")),
            "molecular_weight": _normalize_summary_text(payload.get("molecular_weight")),
            "aliases": _join_alias_candidates(_fetch_pubchem_synonyms(lookup)),
        }, ""

    if source_key == "chembl":
        if not lookup:
            return {}, "Enter a CHEMBL ID to import a summary."
        if not lookup.upper().startswith("CHEMBL"):
            return {}, 'CHEMBL ID must start with "CHEMBL" (example: CHEMBL25).'

        snapshot = _fetch_chembl_summary_snapshot(lookup)
        description = _normalize_summary_text(snapshot.get("description"))
        if not description:
            return {}, f"No importable ChEMBL summary was found for {lookup.upper()}."

        return {
            "name": _normalize_summary_text(snapshot.get("name")) or lookup.upper(),
            "description": description,
            "chembl_id": _normalize_summary_text(snapshot.get("chembl_id")) or lookup.upper(),
            "smiles": _normalize_summary_text(snapshot.get("smiles")),
            "inchi": _normalize_summary_text(snapshot.get("inchi")),
            "inchi_key": _normalize_summary_text(snapshot.get("inchi_key")),
            "iupac_name": _normalize_summary_text(snapshot.get("iupac_name")),
            "molecular_formula": _normalize_summary_text(snapshot.get("molecular_formula")),
            "molecular_weight": _normalize_summary_text(snapshot.get("molecular_weight")),
            "mechanism_of_action_summary": _normalize_summary_text(snapshot.get("mechanism_of_action_summary")),
            "aliases": _normalize_summary_text(snapshot.get("aliases")),
        }, ""

    if source_key == "wikipedia":
        if not lookup:
            return {}, "Enter a compound name to import a Wikipedia summary."

        snapshot = _fetch_wikipedia_summary_snapshot(lookup)
        description = _normalize_summary_text(snapshot.get("description"))
        if not description:
            return {}, f'No importable Wikipedia summary was found for "{lookup}".'

        return {
            "name": _normalize_summary_text(snapshot.get("name")) or lookup,
            "description": description,
        }, ""

    return {}, "Choose PubChem, ChEMBL, or Wikipedia before importing a summary."



def _fetch_pubchem_bindingdb_ids(pubchem_cid: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in _fetch_pubchem_registry_ids(pubchem_cid):
        text = raw.strip().upper()
        match = re.search(r"\bBDBM(\d+)\b", text)
        if not match:
            continue
        monomer_id = match.group(1).strip()
        if not monomer_id or monomer_id in seen:
            continue
        seen.add(monomer_id)
        candidates.append(monomer_id)
    return candidates


def _merge_compound_aliases(compound: Compound, candidates: list[str]) -> str:
    names_to_skip = {
        (compound.name or "").strip().lower(),
        (compound.iupac_name or "").strip().lower(),
    }
    existing = [
        part.strip()
        for part in (compound.aliases or "").split(",")
        if part.strip()
    ]
    merged: list[str] = []
    seen: set[str] = set()

    def _push(raw_value: str) -> None:
        normalized = (raw_value or "").strip()
        if not normalized:
            return
        cleaned = normalize_compound_name(normalized)
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen or key in names_to_skip:
            return
        if len(cleaned) > 120:
            return
        candidate_list = merged + [cleaned]
        joined = ", ".join(candidate_list)
        if len(joined) > 255:
            return
        seen.add(key)
        merged.append(cleaned)

    for alias in existing:
        _push(alias)
    for alias in candidates or []:
        _push(alias)

    return ", ".join(merged)


def _compound_identifier_conflicts(compound: Compound, field_name: str, incoming: str) -> bool:
    value = (incoming or "").strip()
    if not value:
        return False

    queryset = Compound.objects.all()
    if compound.pk:
        queryset = queryset.exclude(pk=compound.pk)
    return queryset.filter(**{f"{field_name}__iexact": value}).exists()


def _apply_pubchem_metadata_backfill(compound: Compound) -> Compound:
    cid = (compound.pubchem_cid or "").strip()
    if not cid:
        return compound

    update_fields: set[str] = set()
    try:
        payload = _fetch_pubchem_compound_properties(cid)
    except Exception:
        payload = {}

    def _set_if_blank(field_name: str, value: str, max_len: int | None = None) -> None:
        incoming = (value or "").strip()
        if not incoming:
            return
        current = getattr(compound, field_name, None)
        current_text = str(current).strip() if current is not None else ""
        if current_text:
            return
        if max_len is not None:
            incoming = incoming[:max_len]
        setattr(compound, field_name, incoming)
        update_fields.add(field_name)

    _set_if_blank("smiles", payload.get("smiles", ""), 1000)
    _set_if_blank("inchi", payload.get("inchi", ""), 4000)
    _set_if_blank("inchi_key", payload.get("inchi_key", ""), 64)
    _set_if_blank("iupac_name", payload.get("iupac_name", ""), 1000)
    _set_if_blank("molecular_formula", payload.get("molecular_formula", ""), 100)
    _set_if_blank("molecular_weight", payload.get("molecular_weight", ""), 50)

    if not (compound.chembl_id or "").strip():
        resolved_chembl_id = _resolve_pubchem_chembl_id(cid, payload.get("inchi_key", "") or compound.inchi_key)
        if resolved_chembl_id and not _compound_identifier_conflicts(compound, "chembl_id", resolved_chembl_id):
            compound.chembl_id = resolved_chembl_id[:20]
            update_fields.add("chembl_id")

    if not (compound.bindingdb_id or "").strip():
        bindingdb_ids = _fetch_pubchem_bindingdb_ids(cid)
        if bindingdb_ids:
            bindingdb_id = bindingdb_ids[0]
            if not _compound_identifier_conflicts(compound, "bindingdb_id", bindingdb_id):
                compound.bindingdb_id = bindingdb_id[:32]
                update_fields.add("bindingdb_id")

    merged_aliases = _merge_compound_aliases(compound, _fetch_pubchem_synonyms(cid))
    if merged_aliases and merged_aliases != (compound.aliases or ""):
        compound.aliases = merged_aliases
        update_fields.add("aliases")

    if not (compound.description or "").strip():
        summary = _fetch_pubchem_summary(cid)
        if summary:
            compound.description = summary
            update_fields.add("description")

    if update_fields:
        compound.save(update_fields=sorted(update_fields))
    return compound


def _run_chembl_backfill_import(compound: Compound) -> Compound:
    chembl_id = (compound.chembl_id or "").strip().upper()
    if not chembl_id or not chembl_id.startswith("CHEMBL"):
        return compound

    chembl_out = StringIO()
    try:
        call_command(
            "import_chembl_interactions",
            compounds=chembl_id,
            batch_size=1,
            create_compound_interactions=False,
            update_existing=True,
            stdout=chembl_out,
            stderr=chembl_out,
        )
    except Exception:
        return compound

    refreshed = Compound.objects.filter(chembl_id__iexact=chembl_id).first()
    return refreshed or compound


def _pick_best_chembl_id(candidates: list[str]) -> str:
    clean: list[str] = []
    seen: set[str] = set()
    for raw in candidates or []:
        value = (raw or "").strip().upper()
        if not _CHEMBL_ID_RE.fullmatch(value):
            continue
        if value in seen:
            continue
        seen.add(value)
        clean.append(value)

    if not clean:
        return ""

    def _sort_key(chembl_id: str) -> tuple[int, int]:
        num = chembl_id[6:]
        try:
            parsed = int(num)
        except ValueError:
            parsed = 10**12
        return (parsed, len(chembl_id))

    clean.sort(key=_sort_key)
    return clean[0]


def _fetch_chembl_id_by_inchikey(inchi_key: str) -> str:
    if requests is None:
        return ""

    key = (inchi_key or "").strip()
    if not key:
        return ""

    url = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
    params = {
        "molecule_structures__standard_inchi_key": key,
        "limit": 5,
    }
    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception:
        return ""

    molecules = (payload.get("molecules") or [])
    candidates = [
        (row or {}).get("molecule_chembl_id", "")
        for row in molecules
        if isinstance(row, dict)
    ]
    return _pick_best_chembl_id(candidates)


def _fetch_pubchem_chembl_ids(pubchem_cid: str) -> list[str]:
    candidates = []
    for raw in _fetch_pubchem_registry_ids(pubchem_cid):
        text = (str(raw) if raw is not None else "").strip().upper()
        match = re.search(r"CHEMBL\d+", text)
        if match:
            candidates.append(match.group(0))
    return candidates


def _resolve_pubchem_chembl_id(pubchem_cid: str, inchi_key: str) -> str:
    from_inchi = _fetch_chembl_id_by_inchikey(inchi_key)
    if from_inchi:
        return from_inchi
    return _pick_best_chembl_id(_fetch_pubchem_chembl_ids(pubchem_cid))


def _build_unique_compound_name(
    base_name: str,
    identifier: str,
    *,
    fallback_label: str = "PubChem CID",
) -> str:
    seed = (base_name or "").strip() or f"{fallback_label} {identifier}"
    seed = seed[:500]
    if not Compound.objects.filter(name__iexact=seed).exists():
        return seed

    for idx in range(2, 1000):
        suffix = f" ({idx})"
        stem = seed[: max(1, 500 - len(suffix))]
        candidate = f"{stem}{suffix}"
        if not Compound.objects.filter(name__iexact=candidate).exists():
            return candidate

    fallback = f"{fallback_label} {identifier}"
    return fallback[:500]


def _import_compound_from_pubchem_cid(pubchem_cid: str) -> tuple[Compound | None, str]:
    cid = (pubchem_cid or "").strip()
    if not cid:
        return None, "Enter a PubChem CID to import."
    if not cid.isdigit():
        return None, "PubChem CID must be numeric (example: 2244)."

    payload = _fetch_pubchem_compound_properties(cid)
    if not payload:
        return None, f"No PubChem record found for CID {cid}."

    base_name = (payload.get("title") or payload.get("iupac_name") or f"PubChem CID {cid}").strip()
    resolved_chembl_id = _resolve_pubchem_chembl_id(cid, payload.get("inchi_key", ""))
    compound = Compound.objects.filter(pubchem_cid=cid).first()

    if compound is None:
        if resolved_chembl_id:
            matched_by_chembl = Compound.objects.filter(chembl_id__iexact=resolved_chembl_id).first()
            if matched_by_chembl:
                compound = matched_by_chembl
        matched_by_name = Compound.objects.filter(name__iexact=base_name).first()
        if compound is None and matched_by_name:
            matched_cid = (matched_by_name.pubchem_cid or "").strip()
            if not matched_cid:
                compound = matched_by_name
        if compound is None:
            compound = Compound(name=_build_unique_compound_name(base_name, cid, fallback_label="PubChem CID"))

    updated_fields = set()

    def _has_identifier_conflict(field_name: str, incoming: str) -> bool:
        if not incoming:
            return False
        qs = Compound.objects.all()
        if compound.pk:
            qs = qs.exclude(pk=compound.pk)
        if field_name in {"chembl_id", "pubchem_cid", "bindingdb_id"}:
            return qs.filter(**{f"{field_name}__iexact": incoming}).exists()
        return qs.filter(**{field_name: incoming}).exists()

    def _set_if_blank(field_name: str, value: str, max_len: int) -> None:
        incoming = (value or "").strip()
        if not incoming:
            return
        if _has_identifier_conflict(field_name, incoming):
            return
        current = getattr(compound, field_name, None)
        current_text = str(current).strip() if current is not None else ""
        if current_text:
            return
        setattr(compound, field_name, incoming[:max_len])
        updated_fields.add(field_name)

    _set_if_blank("pubchem_cid", cid, 32)
    _set_if_blank("chembl_id", resolved_chembl_id, 20)
    _set_if_blank("smiles", payload.get("smiles", ""), 1000)
    _set_if_blank("inchi", payload.get("inchi", ""), 4000)
    _set_if_blank("inchi_key", payload.get("inchi_key", ""), 64)
    _set_if_blank("iupac_name", payload.get("iupac_name", ""), 1000)
    _set_if_blank("molecular_formula", payload.get("molecular_formula", ""), 100)
    _set_if_blank("molecular_weight", payload.get("molecular_weight", ""), 50)

    if not (compound.description or "").strip():
        summary_text = _fetch_best_external_summary(
            pubchem_cid=cid,
            chembl_id=resolved_chembl_id,
            name=base_name,
        ) or _build_pubchem_summary_fallback(cid, payload)
        if summary_text:
            compound.description = summary_text
            updated_fields.add("description")

    if compound.pk is None or updated_fields:
        compound.save()

    chembl_backfill_id = (compound.chembl_id or "").strip().upper()
    if chembl_backfill_id:
        chembl_out = StringIO()
        try:
            call_command(
                "import_chembl_interactions",
                compounds=chembl_backfill_id,
                batch_size=1,
                create_compound_interactions=False,
                update_existing=True,
                stdout=chembl_out,
                stderr=chembl_out,
            )
        except Exception:
            pass
        refreshed = Compound.objects.filter(chembl_id__iexact=chembl_backfill_id).first()
        if refreshed:
            compound = refreshed

    enrich_compound(compound)
    mechanism_result = _import_missing_mechanisms_for_compound(compound)
    imported_count = int(mechanism_result.get("imported") or 0)
    if imported_count > 0:
        suffix = f" linked to {chembl_backfill_id}" if chembl_backfill_id else ""
        return compound, f"Imported CID {cid}{suffix} with {imported_count} mechanism/interaction update(s)."
    if chembl_backfill_id:
        return compound, f"Imported CID {cid} and linked to {chembl_backfill_id}."
    return compound, f"Imported CID {cid}."


_BINDINGDB_MONOMER_ID_RE = re.compile(r"^(?:BDBM)?(\d+)$", flags=re.IGNORECASE)


def _normalize_bindingdb_monomer_id(raw_value: str) -> str:
    text = (raw_value or "").strip()
    if not text:
        return ""
    match = _BINDINGDB_MONOMER_ID_RE.fullmatch(text)
    return (match.group(1) if match else "").strip()


def _extract_bindingdb_tsv_link(download_page_html: str) -> str:
    if not download_page_html:
        return ""
    match = re.search(
        r'href=["\']([^"\']*?/rwd/tmp/BindingDB_[^"\']+?\.tsv)["\']',
        download_page_html,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""

    link = (match.group(1) or "").strip()
    if not link:
        return ""
    if link.startswith("http://") or link.startswith("https://"):
        return link
    if not link.startswith("/"):
        link = f"/{link}"
    return f"https://www.bindingdb.org{link}"


def _fetch_bindingdb_tsv_for_monomer(bindingdb_monomer_id: str) -> str:
    if requests is None:
        return ""

    monomer_id = _normalize_bindingdb_monomer_id(bindingdb_monomer_id)
    if not monomer_id:
        return ""

    download_prepare_url = "https://www.bindingdb.org/rwd/bind/chemsearch/marvin/downloadMolStructure.jsp"
    prepare_response = requests.get(
        download_prepare_url,
        params={"dimension": "TAB", "monomerid": monomer_id},
        timeout=30,
    )
    prepare_response.raise_for_status()

    tsv_url = _extract_bindingdb_tsv_link(prepare_response.text)
    if not tsv_url:
        return ""

    tsv_response = requests.get(tsv_url, timeout=30)
    tsv_response.raise_for_status()
    payload = tsv_response.text or ""
    if "BindingDB Reactant_set_id" not in payload:
        return ""
    return payload


def _parse_bindingdb_tsv_rows(tsv_payload: str) -> list[dict[str, str]]:
    if not tsv_payload:
        return []

    lines = [line for line in tsv_payload.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    rows: list[dict[str, str]] = []
    reader = csv.DictReader(lines, delimiter="\t")
    for row in reader:
        if not isinstance(row, dict):
            continue
        cleaned = {
            (key or "").strip(): (value or "").strip()
            for key, value in row.items()
            if key
        }
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def _import_compound_from_bindingdb_id(bindingdb_id: str) -> tuple[Compound | None, str]:
    monomer_id = _normalize_bindingdb_monomer_id(bindingdb_id)
    if not monomer_id:
        return None, "BindingDB ID must be numeric or prefixed as BDBM<number> (example: 50058958 or BDBM50058958)."

    tsv_payload = _fetch_bindingdb_tsv_for_monomer(monomer_id)
    if not tsv_payload:
        return None, f"No BindingDB record found for monomer ID {monomer_id}."

    parsed_rows = _parse_bindingdb_tsv_rows(tsv_payload)
    if not parsed_rows:
        return None, f"BindingDB returned no interaction rows for monomer ID {monomer_id}."

    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as tmp_file:
        tmp_file.write(tsv_payload)
        tmp_path = tmp_file.name

    out = StringIO()
    try:
        call_command(
            "import_non_chembl_interactions",
            bindingdb_file=tmp_path,
            progress_every=0,
            review_limit=5,
            stdout=out,
            stderr=out,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    sample = parsed_rows[0]
    ligand_name = (sample.get("BindingDB Ligand Name") or "").strip()
    smiles = (sample.get("Ligand SMILES") or "").strip()
    inchi = (sample.get("Ligand InChI") or "").strip()
    inchi_key = (sample.get("Ligand InChI Key") or "").strip()
    if inchi_key.lower().startswith("inchikey="):
        inchi_key = inchi_key.split("=", 1)[-1].strip()
    chembl_id = (sample.get("ChEMBL ID of Ligand") or "").strip().upper()
    if chembl_id and not chembl_id.startswith("CHEMBL"):
        chembl_id = ""
    pubchem_cid = (sample.get("PubChem CID") or "").strip()

    compound = Compound.objects.filter(bindingdb_id=monomer_id).first()
    if compound is None and chembl_id:
        compound = Compound.objects.filter(chembl_id__iexact=chembl_id).first()
    if compound is None and smiles:
        compound = Compound.objects.filter(smiles=smiles).first()
    if compound is None and ligand_name:
        compound = Compound.objects.filter(name__iexact=ligand_name).first()
    if compound is None:
        compound = Compound(
            name=_build_unique_compound_name(
                ligand_name,
                monomer_id,
                fallback_label="BindingDB Monomer",
            )
        )

    updated_fields: set[str] = set()

    def _set_if_blank(field_name: str, value: str, max_len: int) -> None:
        incoming = (value or "").strip()
        if not incoming:
            return
        current = getattr(compound, field_name, None)
        current_text = str(current).strip() if current is not None else ""
        if current_text:
            return
        setattr(compound, field_name, incoming[:max_len])
        updated_fields.add(field_name)

    if not (compound.bindingdb_id or "").strip():
        compound.bindingdb_id = monomer_id[:32]
        updated_fields.add("bindingdb_id")
    _set_if_blank("chembl_id", chembl_id, 20)
    _set_if_blank("pubchem_cid", pubchem_cid, 32)
    _set_if_blank("smiles", smiles, 1000)
    _set_if_blank("inchi", inchi, 4000)
    _set_if_blank("inchi_key", inchi_key, 64)

    if not (compound.description or "").strip():
        compound.description = f"Imported from BindingDB monomer ID {monomer_id}."
        updated_fields.add("description")

    if compound.pk is None or updated_fields:
        compound.save()

    enrich_compound(compound)

    target_names = {
        (row.get("Target Name") or "").strip()
        for row in parsed_rows
        if (row.get("Target Name") or "").strip()
    }
    return (
        compound,
        f"Imported BindingDB {monomer_id}: {len(parsed_rows)} interaction row(s), {len(target_names)} target(s).",
    )


def _hydrate_compound_from_external_sources(compound: Compound) -> Compound:
    if compound.pk is None:
        return compound

    has_supported_identifier = bool((compound.chembl_id or "").strip() or (compound.pubchem_cid or "").strip())
    if not has_supported_identifier:
        return compound

    if (compound.pubchem_cid or "").strip():
        try:
            compound = _apply_pubchem_metadata_backfill(compound)
        except Exception:
            pass

    if (compound.chembl_id or "").strip():
        try:
            compound = _run_chembl_backfill_import(compound)
        except Exception:
            pass

    try:
        enrich_compound(compound)
    except Exception:
        pass

    if (compound.pubchem_cid or "").strip():
        try:
            compound = _apply_pubchem_metadata_backfill(compound)
        except Exception:
            pass

    if not (compound.description or "").strip():
        try:
            summary_text = _fetch_best_external_summary(
                pubchem_cid=(compound.pubchem_cid or "").strip(),
                chembl_id=(compound.chembl_id or "").strip(),
                name=compound.name,
            )
        except Exception:
            summary_text = ""
        if summary_text:
            compound.description = summary_text
            compound.save(update_fields=["description"])

    try:
        _import_missing_mechanisms_for_compound(compound)
    except Exception:
        pass

    refreshed = Compound.objects.filter(pk=compound.pk).first()
    return refreshed or compound


@login_required
@require_POST
def compound_admet_ai_refresh(request, slug):
    compound = get_object_or_404(Compound, slug=slug)

    next_url = request.POST.get("next") or reverse("compound_detail", kwargs={"slug": slug})
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("compound_detail", kwargs={"slug": slug})

    if not compound.smiles:
        return redirect(_append_query_params(next_url, {"admet": "missing_smiles"}))

    from .admet_ai import is_admet_ai_available, get_admet_ai_version, predict_admet

    if not is_admet_ai_available():
        return redirect(_append_query_params(next_url, {"admet": "unavailable"}))

    smiles = compound.smiles.strip()
    smiles_hash = hashlib.sha256(smiles.encode("utf-8")).hexdigest()

    try:
        predictions = predict_admet(smiles)
        CompoundADMETPrediction.objects.update_or_create(
            compound=compound,
            defaults={
                "smiles": smiles,
                "smiles_sha256": smiles_hash,
                "model_version": get_admet_ai_version(),
                "predictions": predictions,
                "error": "",
            },
        )
        return redirect(_append_query_params(next_url, {"admet": "ok"}))
    except Exception as exc:
        CompoundADMETPrediction.objects.update_or_create(
            compound=compound,
            defaults={
                "smiles": smiles,
                "smiles_sha256": smiles_hash,
                "model_version": get_admet_ai_version(),
                "predictions": {},
                "error": str(exc),
            },
        )
        return redirect(_append_query_params(next_url, {"admet": "error"}))


@login_required
@require_POST
def compound_molprop_refresh(request, slug):
    compound = get_object_or_404(Compound, slug=slug)

    next_url = request.POST.get("next") or reverse("compound_detail", kwargs={"slug": slug})
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("compound_detail", kwargs={"slug": slug})

    if not compound.smiles:
        return redirect(_append_query_params(next_url, {"molprop": "missing_smiles"}))

    from .molprop import is_molprop_available, get_molprop_version, predict_molprop

    if not is_molprop_available():
        return redirect(_append_query_params(next_url, {"molprop": "unavailable"}))

    smiles = compound.smiles.strip()
    smiles_hash = hashlib.sha256(smiles.encode("utf-8")).hexdigest()

    try:
        predictions, uncertainty = predict_molprop(smiles)
        CompoundMolPropPrediction.objects.update_or_create(
            compound=compound,
            defaults={
                "smiles": smiles,
                "smiles_sha256": smiles_hash,
                "model_version": get_molprop_version(),
                "predictions": predictions,
                "uncertainty": uncertainty,
                "error": "",
            },
        )
        return redirect(_append_query_params(next_url, {"molprop": "ok"}))
    except Exception as exc:
        CompoundMolPropPrediction.objects.update_or_create(
            compound=compound,
            defaults={
                "smiles": smiles,
                "smiles_sha256": smiles_hash,
                "model_version": get_molprop_version(),
                "predictions": {},
                "uncertainty": {},
                "error": str(exc),
            },
        )
        return redirect(_append_query_params(next_url, {"molprop": "error"}))


@require_POST
@user_passes_test(is_staff_user)
def queue_compound_research_import(request, slug):
    compound = get_object_or_404(Compound, slug=slug)

    next_url = request.POST.get("next") or reverse("compound_detail", kwargs={"slug": slug})
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("compound_detail", kwargs={"slug": slug})

    from research.models import ResearchImportJob

    has_existing_job = ResearchImportJob.objects.filter(
        compound=compound,
        status__in=["queued", "running"],
    ).exists()
    if has_existing_job:
        return redirect(_append_query_params(next_url, {"research_import": "exists"}))

    ResearchImportJob.objects.create(
        compound=compound,
        requested_by=request.user,
        status="queued",
        max_results=10,
    )
    return redirect(_append_query_params(next_url, {"research_import": "queued"}))


@require_POST
@user_passes_test(is_staff_user)
def queue_compound_mechanism_import(request, slug):
    compound = get_object_or_404(Compound, slug=slug)

    next_url = request.POST.get("next") or reverse("compound_detail", kwargs={"slug": slug})
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("compound_detail", kwargs={"slug": slug})

    try:
        result = _import_missing_mechanisms_for_compound(compound)
    except Exception:
        return redirect(_append_query_params(next_url, {"mechanism_import": "error"}))

    imported = int(result.get("imported") or 0)
    source = (result.get("source") or "").strip().lower()
    if imported > 0:
        return redirect(
            _append_query_params(
                next_url,
                {
                    "mechanism_import": "imported",
                    "mechanism_import_count": str(imported),
                    "mechanism_import_source": source,
                },
            )
        )
    return redirect(_append_query_params(next_url, {"mechanism_import": "not_found"}))


@user_passes_test(is_staff_user)
def add_compound(request):
    chembl_import_id = ''
    chembl_import_message = ''
    chembl_import_message_type = 'danger'
    chembl_import_output = ''
    pubchem_import_cid = ''
    pubchem_import_message = ''
    pubchem_import_message_type = 'danger'
    pubchem_import_output = ''
    bindingdb_import_id = ''
    bindingdb_import_message = ''
    bindingdb_import_message_type = 'danger'
    bindingdb_import_output = ''
    summary_import_source = 'pubchem'
    summary_import_query = ''
    summary_import_message = ''
    summary_import_message_type = 'danger'
    summary_import_preview = ''

    def _render_add_compound_page(form):
        return render(request, 'compounds/add_compound.html', {
            'form': form,
            'chembl_import_id': chembl_import_id,
            'chembl_import_message': chembl_import_message,
            'chembl_import_message_type': chembl_import_message_type,
            'chembl_import_output': chembl_import_output,
            'pubchem_import_cid': pubchem_import_cid,
            'pubchem_import_message': pubchem_import_message,
            'pubchem_import_message_type': pubchem_import_message_type,
            'pubchem_import_output': pubchem_import_output,
            'bindingdb_import_id': bindingdb_import_id,
            'bindingdb_import_message': bindingdb_import_message,
            'bindingdb_import_message_type': bindingdb_import_message_type,
            'bindingdb_import_output': bindingdb_import_output,
            'summary_import_source': summary_import_source,
            'summary_import_query': summary_import_query,
            'summary_import_message': summary_import_message,
            'summary_import_message_type': summary_import_message_type,
            'summary_import_preview': summary_import_preview,
        })

    if request.method == 'POST':
        if request.POST.get('quick_import_chembl'):
            chembl_import_id = (request.POST.get('chembl_import_id') or '').strip().upper()
            form = CompoundForm()

            if not chembl_import_id:
                chembl_import_message = 'Enter a CHEMBL ID to import.'
            elif not chembl_import_id.startswith('CHEMBL'):
                chembl_import_message = 'CHEMBL ID must start with "CHEMBL" (example: CHEMBL25).'
            else:
                out = StringIO()
                try:
                    call_command(
                        'import_chembl_interactions',
                        compounds=chembl_import_id,
                        batch_size=1,
                        create_compound_interactions=False,
                        stdout=out,
                        stderr=out,
                    )
                except Exception as exc:
                    chembl_import_message = f'Failed to import {chembl_import_id}: {exc}'
                    chembl_import_output = out.getvalue().strip()
                else:
                    imported = Compound.objects.filter(chembl_id__iexact=chembl_import_id).first()
                    if imported:
                        return redirect('compound_detail', slug=imported.slug)
                    chembl_import_message = f'Import completed but no compound with {chembl_import_id} was created.'
                    chembl_import_message_type = 'warning'
                    chembl_import_output = out.getvalue().strip()

            return _render_add_compound_page(form)

        if request.POST.get('quick_import_pubchem'):
            pubchem_import_cid = (request.POST.get('pubchem_import_cid') or '').strip()
            form = CompoundForm()

            if not pubchem_import_cid:
                pubchem_import_message = 'Enter a PubChem CID to import.'
            elif not pubchem_import_cid.isdigit():
                pubchem_import_message = 'PubChem CID must be numeric (example: 2244).'
            else:
                try:
                    imported, import_message = _import_compound_from_pubchem_cid(pubchem_import_cid)
                except Exception as exc:
                    pubchem_import_message = f'Failed to import CID {pubchem_import_cid}: {exc}'
                else:
                    pubchem_import_output = (import_message or '').strip()
                    if imported:
                        return redirect('compound_detail', slug=imported.slug)
                    pubchem_import_message = import_message or f'No compound could be imported from CID {pubchem_import_cid}.'
                    pubchem_import_message_type = 'warning'

            return _render_add_compound_page(form)

        if request.POST.get('quick_import_bindingdb'):
            bindingdb_import_id = (request.POST.get('bindingdb_import_id') or '').strip()
            form = CompoundForm()

            if not bindingdb_import_id:
                bindingdb_import_message = 'Enter a BindingDB ID to import.'
            elif not _normalize_bindingdb_monomer_id(bindingdb_import_id):
                bindingdb_import_message = (
                    'BindingDB ID must be numeric or in BDBM<number> format '
                    '(example: 50058958 or BDBM50058958).'
                )
            else:
                try:
                    imported, import_message = _import_compound_from_bindingdb_id(bindingdb_import_id)
                except Exception as exc:
                    bindingdb_import_message = f'Failed to import BindingDB {bindingdb_import_id}: {exc}'
                else:
                    bindingdb_import_output = (import_message or '').strip()
                    if imported:
                        return redirect('compound_detail', slug=imported.slug)
                    bindingdb_import_message = (
                        import_message or f'No compound could be imported from BindingDB {bindingdb_import_id}.'
                    )
                    bindingdb_import_message_type = 'warning'

            return _render_add_compound_page(form)

        if request.POST.get('quick_import_summary'):
            summary_import_source = (request.POST.get('summary_import_source') or 'pubchem').strip().lower() or 'pubchem'
            summary_import_query = (request.POST.get('summary_import_query') or '').strip()
            initial_values, error_message = _prepare_summary_import_initial(summary_import_source, summary_import_query)
            if error_message:
                summary_import_message = error_message
                summary_import_message_type = 'warning'
                form = CompoundForm()
            else:
                summary_import_message = 'Summary loaded into the form below. Review the fields and save when ready.'
                summary_import_message_type = 'success'
                summary_import_preview = (initial_values.get('description') or '').strip()
                form = CompoundForm(initial=initial_values)
            return _render_add_compound_page(form)

        form = CompoundForm(request.POST)
        if form.is_valid():
            compound = form.save()
            compound = _hydrate_compound_from_external_sources(compound)
            return redirect('compound_detail', slug=compound.slug)
    else:
        form = CompoundForm()
    return _render_add_compound_page(form)



@require_POST
def submit_rating(request, slug):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=403)
    
    try:
        compound = Compound.objects.get(slug=slug)

        # Parse JSON body
        data = json.loads(request.body)
        score = int(data.get('rating'))

        if score < 1 or score > 5:
            raise ValueError
        
        rating, created = CompoundRating.objects.update_or_create(
            compound=compound,
            user=request.user,
            defaults={'score': score}
        )

        # Return new average
        new_avg = CompoundRating.objects.filter(compound=compound).aggregate(models.Avg('score'))['score__avg']

        return JsonResponse({'success': True, 'new_score': rating.score, 'new_avg': new_avg})
    
    except (Compound.DoesNotExist, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data'}, status=400)


def compound_search(request):
    query = request.GET.get('q', '')
    results = []

    if query:
        results = Compound.objects.filter(
            Q(name__icontains=query) |
            Q(aliases__icontains=query)
        )

    return render(request, 'compounds/compound_search_results.html', {
        'query': query,
        'results': results,
    })


@login_required
def compound_knowledge_graph_query(request, slug=None):
    """Interactive page for querying compound knowledge graph runs/edges."""
    initial_compound = None

    if slug:
        initial_compound = Compound.objects.filter(slug=slug).only("id", "name", "slug").first()
    else:
        raw_compound_id = (request.GET.get("compound") or request.GET.get("compound_id") or "").strip()
        if raw_compound_id.isdigit():
            initial_compound = Compound.objects.filter(id=int(raw_compound_id)).only("id", "name", "slug").first()

    initial_payload = None
    if initial_compound:
        initial_payload = {
            "id": initial_compound.id,
            "name": initial_compound.name,
            "slug": initial_compound.slug,
        }

    context = {
        "initial_compound": initial_compound,
        "initial_compound_payload": initial_payload or {},
        "compound_search_api_url": reverse("compound-search-api"),
        "knowledge_graph_api_template": reverse("compound-knowledge-graph", kwargs={"compound_id": 0}),
        "knowledge_graph_enrich_api_template": reverse("compound-knowledge-graph-enrich", kwargs={"compound_id": 0}),
    }
    return render(request, "compounds/knowledge_graph_query.html", context)


@login_required
def compound_network_graph_view(request):
    """Global network graph (lazy-loaded) for compounds/targets/mechanisms."""
    context = {
        "network_graph_api_url": reverse("compound-network-graph"),
        "compound_search_api_url": reverse("compound-search-api"),
        "network_graph_subgraph_api_template": reverse("compound-network-graph-subgraph", kwargs={"compound_id": 0}),
        "network_graph_target_subgraph_api_template": reverse(
            "compound-network-graph-target-subgraph",
            kwargs={"target_id": 0},
        ),
    }
    return render(request, "compounds/network_graph.html", context)

def compound_list(request):
    from django.core.paginator import Paginator
    from django.http import JsonResponse
    
    # Order compounds by view count (descending) then by name
    compounds = Compound.objects.all().order_by('-views', 'name')
    
    # Handle AJAX requests for lazy loading
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        page = request.GET.get('page', 1)
        paginator = Paginator(compounds, 12)  # 12 compounds per page
        
        try:
            compounds_page = paginator.page(page)
        except:
            return JsonResponse({'compounds': [], 'has_next': False})
        
        # Prepare compound data for JSON response
        compounds_data = []
        for compound in compounds_page:
            compounds_data.append({
                'id': compound.id,
                'name': compound.name,
                'slug': compound.slug,
                'description': compound.description or '',
                'aliases': compound.aliases or '',
                'smiles': compound.smiles or '',
                'categories': [{'name': cat.name} for cat in compound.categories.all()],
                'detail_url': f'/compounds/{compound.slug}/'
            })
        
        return JsonResponse({
            'compounds': compounds_data,
            'has_next': compounds_page.has_next(),
            'next_page': compounds_page.next_page_number() if compounds_page.has_next() else None
        })
    
    # For initial page load, return first page
    paginator = Paginator(compounds, 12)
    first_page = paginator.page(1)
    
    return render(request, "compounds/compound_list.html", {
        "compounds": first_page,
        "has_next": first_page.has_next()
    })

def mechanism_list(request):
    mechanisms = CompoundMechanismOfAction.objects.all()
    return render(request, "compounds/mechanism_list.html", {"mechanisms": mechanisms})

def add_mechanism(request):
    if request.method == "POST":
        form = MechanismOfActionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('mechanism_list')
    else:
        form = MechanismOfActionForm()
    return render(request, "compounds/add_mechanism.html", {"form": form})


@require_POST
@user_passes_test(is_staff_user)
def ajax_add_mechanism(request):
    form = MechanismOfActionForm(request.POST)
    if form.is_valid():
        mechanism = form.save()
        return JsonResponse({
            'success': True,
            'id': mechanism.id,
            'display_name': str(mechanism)
        })
    return JsonResponse({
        'success': False,
        'errors': form.errors
    })


@require_POST
@user_passes_test(is_staff_user)
def ajax_add_category(request):
    form = CategoryForm(request.POST)
    if form.is_valid():
        category = form.save()
        return JsonResponse({
            'success': True,
            'id': category.id,
            'name': category.name
        })
    return JsonResponse({
        'success': False,
        'errors': form.errors
    })


@login_required
def ajax_add_target(request):
    if request.method == 'POST':
        form = TargetForm(request.POST)
        if form.is_valid():
            target = form.save()
            return JsonResponse({
                'success': True,
                'id': target.id,
                'name': target.name
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            })
    return JsonResponse({'success': False})

def api_targets(request):
    """API endpoint to get all targets as JSON"""
    targets = Target.objects.all().values('id', 'name')
    return JsonResponse(list(targets), safe=False)

def api_mechanisms(request):
    """API endpoint to get all mechanisms as JSON"""
    mechanisms = CompoundMechanismOfAction.objects.all()
    mechanism_list = []
    for mechanism in mechanisms:
        mechanism_list.append({
            'id': mechanism.id,
            'display_name': str(mechanism)
        })
    return JsonResponse(mechanism_list, safe=False)

def api_categories(request):
    """API endpoint to get all categories as JSON"""
    categories = CompoundCategories.objects.all().values('id', 'name')
    return JsonResponse(list(categories), safe=False)


@require_POST
@login_required
def review_snippet(request, slug, snippet_id):
    """Handle snippet reviews from compound detail page"""
    try:
        from research.models import ResearchSnippet, SnippetReview
        
        compound = get_object_or_404(Compound, slug=slug)
        snippet = get_object_or_404(ResearchSnippet, id=snippet_id, compound=compound)
        
        # Check if user already reviewed this snippet
        existing_review = SnippetReview.objects.filter(
            snippet=snippet, 
            reviewer=request.user
        ).first()
        
        if existing_review:
            return JsonResponse({
                'success': False, 
                'error': 'You have already reviewed this snippet'
            })
        
        data = json.loads(request.body)
        vote_type = data.get('vote_type')
        
        if vote_type not in ['validate', 'reject']:
            return JsonResponse({
                'success': False, 
                'error': 'Invalid vote type'
            })
        
        # Create the review
        review = SnippetReview.objects.create(
            snippet=snippet,
            reviewer=request.user,
            vote_type=vote_type,
            comment=data.get('comment', '')
        )
        
        # Update snippet status
        snippet.update_status()
        
        # Get updated counts
        review_counts = snippet.reviews.aggregate(
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        return JsonResponse({
            'success': True,
            'positive_count': review_counts['positive'] or 0,
            'negative_count': review_counts['negative'] or 0,
            'new_status': snippet.status
        })
        
    except ImportError:
        return JsonResponse({
            'success': False, 
            'error': 'Research functionality not available'
        })
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'error': str(e)
        })


# REST Framework ViewSets
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .serializers import (
    CompoundCategoriesSerializer,
    TargetSerializer,
    CompoundMechanismOfActionSerializer,
    CompoundSerializer,
    CompoundRatingSerializer,
    CompoundSafetyScreeningSerializer,
    EffectWindowSerializer
)


class CompoundCategoriesViewSet(viewsets.ModelViewSet):
    queryset = CompoundCategories.objects.all()
    serializer_class = CompoundCategoriesSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class TargetViewSet(viewsets.ModelViewSet):
    queryset = Target.objects.all()
    serializer_class = TargetSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class CompoundMechanismOfActionViewSet(viewsets.ModelViewSet):
    queryset = CompoundMechanismOfAction.objects.all()
    serializer_class = CompoundMechanismOfActionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class CompoundViewSet(viewsets.ModelViewSet):
    queryset = Compound.objects.all()
    serializer_class = CompoundSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'

    def perform_create(self, serializer):
        compound = serializer.save()
        serializer.instance = _hydrate_compound_from_external_sources(compound)

    def perform_update(self, serializer):
        compound = serializer.save()
        serializer.instance = _hydrate_compound_from_external_sources(compound)

    def retrieve(self, request, *args, **kwargs):
        compound = self.get_object()
        _auto_enrich_compound_on_access(compound)
        serializer = self.get_serializer(compound)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def ratings(self, request, slug=None):
        compound = self.get_object()
        ratings = CompoundRating.objects.filter(compound=compound)
        serializer = CompoundRatingSerializer(ratings, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def safety_screening(self, request, slug=None):
        compound = self.get_object()
        try:
            safety = compound.safety_screening
            serializer = CompoundSafetyScreeningSerializer(safety)
            return Response(serializer.data)
        except CompoundSafetyScreening.DoesNotExist:
            return Response({'detail': 'No safety screening data available'}, status=404)


class CompoundRatingViewSet(viewsets.ModelViewSet):
    queryset = CompoundRating.objects.all()
    serializer_class = CompoundRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = CompoundRating.objects.all()
        compound_id = self.request.query_params.get('compound', None)
        if compound_id is not None:
            queryset = queryset.filter(compound_id=compound_id)
        return queryset


class CompoundSafetyScreeningViewSet(viewsets.ModelViewSet):
    queryset = CompoundSafetyScreening.objects.all()
    serializer_class = CompoundSafetyScreeningSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = CompoundSafetyScreening.objects.all()
        compound_id = self.request.query_params.get('compound', None)
        if compound_id is not None:
            queryset = queryset.filter(compound_id=compound_id)
        return queryset


class EffectWindowViewSet(viewsets.ModelViewSet):
    queryset = EffectWindow.objects.all()
    serializer_class = EffectWindowSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = EffectWindow.objects.select_related('compound', 'created_by')
        compound_id = self.request.query_params.get('compound', None)
        if compound_id is not None:
            queryset = queryset.filter(compound_id=compound_id)
        return queryset.order_by('-created_at')

    @action(detail=True, methods=['get'])
    def curve_data(self, request, pk=None):
        """Get detailed curve data with custom resolution"""
        effect_window = self.get_object()
        resolution = int(request.query_params.get('resolution', 5))  # Default 5 minutes
        curve_data = effect_window.get_effect_curve_data(resolution_minutes=resolution)
        
        return Response({
            'compound': effect_window.compound.name,
            'effect_shape': effect_window.effect_shape,
            'curve_data': curve_data,
            'metadata': {
                'onset_minutes': effect_window.onset_minutes,
                'peak_min_minutes': effect_window.peak_min_minutes,
                'peak_max_minutes': effect_window.peak_max_minutes,
                'duration_minutes': effect_window.duration_minutes,
                'half_life_minutes': effect_window.half_life_minutes,
            }
        })
