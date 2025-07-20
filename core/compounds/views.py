import json
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.db.models import Q
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import Compound, CompoundSafetyScreening, CompoundRating, CompoundCategories, CompoundMechanismOfAction, CompoundReceptorTargets
from .forms import CompoundForm


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

    context = {
        'compound': compound,
        'safety_report': safety_report,
        'avg_rating': round(avg_rating, 2) if avg_rating else None,
        'user_rating': user_rating,
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

