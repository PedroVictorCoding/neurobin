from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.contrib.auth.decorators import login_required, user_passes_test

from .models import Compound, CompoundSafetyScreening, CompoundRating
from .forms import CompoundForm


def compound_detail(request, slug):
    compound = get_object_or_404(Compound, slug=slug)
    
    safety_report = CompoundSafetyScreening.objects.filter(compound=compound).order_by('-created_by').first()
    avg_safety = {
        'liver': safety_report.aggregate(models.Avg('liver_toxicity'))['liver_toxicity__avg'],
        'kidney': safety_report.aggregate(models.Avg('kidney_toxicity'))['kidney_toxicity__avg'],
        'cardio': safety_report.aggregate(models.Avg('cardiovascular_risk'))['cardiovascular_risk__avg'],
        'hpta': safety_report.aggregate(models.Avg('hpta_suppression'))['hpta_suppression__avg'],
        'neuro': safety_report.aggregate(models.Avg('neurotoxicity'))['neurotoxicity__avg'],
        'lung': safety_report.aggregate(models.Avg('lung_toxicity'))['lung_toxicity__avg'],
        'pancreas': safety_report.aggregate(models.Avg('pancreas_toxicity'))['pancreas_toxicity__avg'],
        'bladder': safety_report.aggregate(models.Avg('bladder_toxicity'))['bladder_toxicity__avg'],
    }

    compound_rating = CompoundRating.objects.filter(compound=compound).all()
    avg_rating = compound_rating.aggregate(models.Avg('score'))['score__avg']

    context = {
        'compound': compound,
        'safety_report': safety_report,
        'avg_safety': avg_safety,
        'avg_rating': round(avg_rating, 2) if avg_rating else None,
    }

    return render(request, 'compounds/compound_details.html', context)


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



