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
            return redirect('analytics_dashboard')
    else:
        form = IntakeLogForm()
    return render(request, "logs/log_intake.html", {"form": form})

@login_required
def analytics_dashboard(request):
    from django.utils import timezone
    from datetime import datetime, timedelta
    from compounds.models import CompoundToCompoundTargetInteraction
    from django.db.models import Q
    
    logs = IntakeLog.objects.filter(user=request.user).order_by('-taken_at')
    
    # Get today's date
    today = timezone.now().date()
    
    # Get today's compounds
    todays_logs = IntakeLog.objects.filter(
        user=request.user,
        taken_at__date=today
    ).select_related('compound')
    
    todays_compounds = [log.compound for log in todays_logs]
    
    # Find interactions between today's compounds
    interactions = []
    if len(todays_compounds) > 1:
        compound_ids = [c.id for c in todays_compounds]
        interactions = CompoundToCompoundTargetInteraction.objects.filter(
            Q(compound_a__id__in=compound_ids, compound_b__id__in=compound_ids)
        ).select_related('compound_a', 'compound_b', 'target').distinct()
    
    # You can aggregate data here for the dashboard
    return render(request, "logs/analytics_dashboard.html", {
        "logs": logs,
        "todays_compounds": todays_compounds,
        "todays_interactions": interactions,
        "todays_logs": todays_logs
    })


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
        queryset = IntakeLog.objects.filter(user=self.request.user).select_related('compound').prefetch_related('compound__effect_windows').order_by('-taken_at')
        
        # Apply date filtering if provided
        taken_at_gte = self.request.query_params.get('taken_at__gte')
        taken_at_lt = self.request.query_params.get('taken_at__lt')
        
        if taken_at_gte:
            queryset = queryset.filter(taken_at__gte=taken_at_gte)
        if taken_at_lt:
            queryset = queryset.filter(taken_at__lt=taken_at_lt)
            
        return queryset

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
