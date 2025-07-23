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


# REST Framework ViewSets
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count
from .serializers import IntakeLogSerializer


class IntakeLogViewSet(viewsets.ModelViewSet):
    serializer_class = IntakeLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Users can only access their own logs
        return IntakeLog.objects.filter(user=self.request.user).order_by('-taken_at')

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Get analytics data for user's intake logs"""
        logs = self.get_queryset()
        
        # Basic analytics
        total_logs = logs.count()
        compounds_used = logs.values('compound__name').distinct().count()
        most_used_compound = logs.values('compound__name').annotate(
            count=Count('compound')
        ).order_by('-count').first()
        
        analytics_data = {
            'total_logs': total_logs,
            'compounds_used': compounds_used,
            'most_used_compound': most_used_compound,
        }
        
        return Response(analytics_data)
