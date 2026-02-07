import json
import hashlib
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.db.models import Q, Count
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
)
from .forms import CompoundForm, MechanismOfActionForm, CategoryForm, TargetForm


def compound_detail(request, slug):
    compound = get_object_or_404(Compound, slug=slug)
    
    # Increment view count
    compound.increment_views()
    
    #safety_report = CompoundSafetyScreening.objects.filter(compound=compound).order_by('-created_by').first()
    #safety_report = compound.compoundsafetyscreening_set.all()
    safety_report = getattr(compound, 'safety_report', None)

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
        if admet_prediction and isinstance(getattr(admet_prediction, "predictions", None), dict):
            primary_predictions = admet_prediction.predictions or {}
            secondary_predictions = (molprop_prediction.predictions if molprop_prediction else {}) or {}
            secondary_label = "MolProp"
        elif molprop_prediction and isinstance(getattr(molprop_prediction, "predictions", None), dict):
            primary_predictions = molprop_prediction.predictions or {}
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


@user_passes_test(is_staff_user)
def add_compound(request):
    if request.method == 'POST':
        form = CompoundForm(request.POST)
        if form.is_valid():
            compound = form.save()
            return redirect('compound_detail', slug=compound.slug)
    else:
        form = CompoundForm()
    return render(request, 'compounds/add_compound.html', {'form': form})



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
