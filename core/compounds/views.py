import json
import hashlib
import math
from io import StringIO
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
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
)
from .forms import CompoundForm, MechanismOfActionForm, CategoryForm, TargetForm


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


def compound_detail(request, slug):
    compound = get_object_or_404(Compound, slug=slug)
    
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
    }

    return render(request, 'compounds/compound_detail.html', context)


def compound_details(request, slug):
    """Enhanced compound details view with view tracking"""
    return compound_detail(request, slug)


def is_staff_user(user):
    return user.is_authenticated and user.is_staff


def _append_query_params(url: str, params: dict) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None})
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


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


@user_passes_test(is_staff_user)
def add_compound(request):
    chembl_import_id = ''
    chembl_import_message = ''
    chembl_import_message_type = 'danger'
    chembl_import_output = ''

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

            return render(request, 'compounds/add_compound.html', {
                'form': form,
                'chembl_import_id': chembl_import_id,
                'chembl_import_message': chembl_import_message,
                'chembl_import_message_type': chembl_import_message_type,
                'chembl_import_output': chembl_import_output,
            })

        form = CompoundForm(request.POST)
        if form.is_valid():
            compound = form.save()
            return redirect('compound_detail', slug=compound.slug)
    else:
        form = CompoundForm()
    return render(request, 'compounds/add_compound.html', {
        'form': form,
        'chembl_import_id': chembl_import_id,
        'chembl_import_message': chembl_import_message,
        'chembl_import_message_type': chembl_import_message_type,
        'chembl_import_output': chembl_import_output,
    })



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
def review_snippet(request, compound_slug, snippet_id):
    """Handle snippet reviews from compound detail page"""
    try:
        from research.models import ResearchSnippet, SnippetReview
        
        compound = get_object_or_404(Compound, slug=compound_slug)
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
