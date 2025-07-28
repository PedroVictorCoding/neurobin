from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Count, Avg, Q
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.shortcuts import redirect

from .models import ScoringCategory, CompoundScore, UserCompoundAnnotation
from compounds.models import Compound


def rankings_list(request):
    """Display all scoring categories with preview of top compounds"""
    categories = ScoringCategory.objects.filter(is_active=True).annotate(
        compound_count=Count('compoundscore'),
        avg_score=Avg('compoundscore__score')
    ).order_by('name')
    
    # Get top 3 compounds for each category and attach to category objects
    for category in categories:
        top_compounds = CompoundScore.objects.filter(
            category=category
        ).select_related('compound').order_by('-score')[:3]
        category.top_compounds = top_compounds
    
    context = {
        'categories': categories,
        'total_categories': categories.count(),
        'total_compounds': CompoundScore.objects.values('compound').distinct().count(),
    }
    
    return render(request, 'compound_ranker/rankings_list.html', context)


def rankings_detail(request, slug):
    """Display detailed rankings for a specific category"""
    category = get_object_or_404(ScoringCategory, slug=slug, is_active=True)
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    min_score = request.GET.get('min_score', '')
    min_confidence = request.GET.get('min_confidence', '')
    
    # Build queryset
    scores = CompoundScore.objects.filter(category=category).select_related('compound')
    
    if search_query:
        scores = scores.filter(
            Q(compound__name__icontains=search_query) |
            Q(compound__chembl_id__icontains=search_query) |
            Q(compound__aliases__icontains=search_query)
        )
    
    if min_score:
        try:
            scores = scores.filter(score__gte=float(min_score))
        except ValueError:
            pass
    
    if min_confidence:
        try:
            scores = scores.filter(confidence__gte=float(min_confidence))
        except ValueError:
            pass
    
    scores = scores.order_by('-score', '-confidence')
    
    # Pagination
    paginator = Paginator(scores, 25)  # Show 25 compounds per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate statistics
    stats = {
        'total_compounds': scores.count(),
        'avg_score': scores.aggregate(Avg('score'))['score__avg'] or 0,
        'avg_confidence': scores.aggregate(Avg('confidence'))['confidence__avg'] or 0,
        'high_confidence_count': scores.filter(confidence__gte=0.8).count(),
    }
    
    context = {
        'category': category,
        'page_obj': page_obj,
        'search_query': search_query,
        'min_score': min_score,
        'min_confidence': min_confidence,
        'stats': stats,
    }
    
    return render(request, 'compound_ranker/ranking_detail.html', context)


def compound_detail(request, compound_id):
    """Display compound details with scores across all categories"""
    compound = get_object_or_404(Compound, id=compound_id)
    
    # Get scores across all categories
    scores = CompoundScore.objects.filter(
        compound=compound
    ).select_related('category').order_by('-score')
    
    # Calculate compound's overall ranking metrics
    ranking_stats = {}
    for score in scores:
        ranking_stats[score.category.slug] = {
            'rank': score.rank_in_category,
            'total_in_category': CompoundScore.objects.filter(category=score.category).count(),
            'percentile': (1 - (score.rank_in_category - 1) / CompoundScore.objects.filter(category=score.category).count()) * 100
        }
    
    # Get user annotations if logged in
    user_annotations = []
    if request.user.is_authenticated:
        user_annotations = UserCompoundAnnotation.objects.filter(
            compound=compound,
            user=request.user
        ).select_related('category')
    
    context = {
        'compound': compound,
        'scores': scores,
        'ranking_stats': ranking_stats,
        'user_annotations': user_annotations,
    }
    
    return render(request, 'compound_ranker/compound_detail.html', context)


@login_required
@require_http_methods(["POST"])
def add_user_annotation(request):
    """Add user annotation for a compound in a category"""
    compound_id = request.POST.get('compound_id')
    category_id = request.POST.get('category_id')
    user_score = request.POST.get('user_score')
    notes = request.POST.get('notes', '')
    
    try:
        compound = Compound.objects.get(id=compound_id)
        category = ScoringCategory.objects.get(id=category_id)
        score = float(user_score)
        
        if not (0 <= score <= 1):
            messages.error(request, "Score must be between 0 and 1")
            return redirect('compound_ranker:compound_detail', compound_id=compound_id)
        
        annotation, created = UserCompoundAnnotation.objects.update_or_create(
            compound=compound,
            category=category,
            user=request.user,
            defaults={
                'user_score': score,
                'notes': notes
            }
        )
        
        if created:
            messages.success(request, f"Added annotation for {compound.name} in {category.name}")
        else:
            messages.success(request, f"Updated annotation for {compound.name} in {category.name}")
        
    except (Compound.DoesNotExist, ScoringCategory.DoesNotExist, ValueError) as e:
        messages.error(request, f"Error adding annotation: {str(e)}")
    
    return redirect('compound_ranker:compound_detail', compound_id=compound_id)


@staff_member_required
def training_status(request):
    """Display model training status and logs"""
    from .models import ModelTrainingLog
    
    logs = ModelTrainingLog.objects.select_related('category', 'trained_by').order_by('-training_started')[:20]
    
    # Get latest status for each category
    latest_by_category = {}
    for category in ScoringCategory.objects.all():
        latest_log = ModelTrainingLog.objects.filter(category=category).first()
        if latest_log:
            latest_by_category[category.slug] = latest_log
    
    context = {
        'logs': logs,
        'latest_by_category': latest_by_category,
        'categories': ScoringCategory.objects.all(),
    }
    
    return render(request, 'compound_ranker/training_status.html', context)


def api_category_stats(request, slug):
    """API endpoint for category statistics"""
    try:
        category = ScoringCategory.objects.get(slug=slug, is_active=True)
        stats = {
            'name': category.name,
            'total_compounds': CompoundScore.objects.filter(category=category).count(),
            'avg_score': CompoundScore.objects.filter(category=category).aggregate(Avg('score'))['score__avg'],
            'high_confidence_count': CompoundScore.objects.filter(category=category, confidence__gte=0.8).count(),
        }
        return JsonResponse(stats)
    except ScoringCategory.DoesNotExist:
        return JsonResponse({'error': 'Category not found'}, status=404)
