from django.shortcuts import render

def home(request):
    from compounds.models import Compound, CompoundTargetInteraction, Target
    
    # Get counts for showcasing data
    compound_count = Compound.objects.count()
    mechanism_count = CompoundTargetInteraction.objects.count()
    target_count = Target.objects.count()
    
    context = {
        'compound_count': compound_count,
        'mechanism_count': mechanism_count,
        'target_count': target_count,
    }
    
    return render(request, "home.html", context)

def effect_curves_demo(request):
    return render(request, "demo/effect_curves_demo.html")

def credits(request):
    return render(request, "core/credits.html")


def about(request):
    return render(request, "core/about.html")
