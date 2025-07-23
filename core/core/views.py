from django.shortcuts import render

def home(request):
    return render(request, "home.html")

def effect_curves_demo(request):
    return render(request, "demo/effect_curves_demo.html")