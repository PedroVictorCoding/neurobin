import json
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import Compound, CompoundSafetyScreening, CompoundRating, CompoundCategories, CompoundMechanismOfAction, Target
from .forms import CompoundForm, MechanismOfActionForm, CategoryForm, TargetForm


def compound_detail(request, slug):
    compound = get_object_or_404(Compound, slug=slug)
    
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

    context = {
        'compound': compound,
        'safety_report': safety_report,
        'avg_rating': round(avg_rating, 2) if avg_rating else None,
        'user_rating': user_rating,
        'research_snippets': snippets,
        'user_reviews': user_reviews,
    }

    return render(request, 'compounds/compound_detail.html', context)


def is_staff_user(user):
    return user.is_authenticated and user.is_staff

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
            Q(name__icontains=query)
        )

    return render(request, 'compounds/compound_search_results.html', {
        'query': query,
        'results': results,
    })

def compound_list(request):
    compounds = Compound.objects.all()
    return render(request, "compounds/compound_list.html", {"compounds": compounds})

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

