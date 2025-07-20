from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import IntakeLog
from .forms import IntakeLogForm

@login_required
def log_intake(request):
    if request.method == "POST":
        form = IntakeLogForm(request.POST)
        if form.is_valid():
            intake = form.save(commit=False)
            intake.user = request.user
            intake.save()
            return redirect('intake_timeline')
    else:
        form = IntakeLogForm()
    return render(request, "logs/log_intake.html", {"form": form})

@login_required
def intake_timeline(request):
    logs = IntakeLog.objects.filter(user=request.user).order_by('-taken_at')
    return render(request, "logs/intake_timeline.html", {"logs": logs})

@login_required
def analytics_dashboard(request):
    logs = IntakeLog.objects.filter(user=request.user)
    # You can aggregate data here for the dashboard
    return render(request, "logs/analytics_dashboard.html", {"logs": logs})
