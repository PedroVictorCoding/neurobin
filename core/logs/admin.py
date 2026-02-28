from django.contrib import admin
from .models import (
    IntakeLog,
    RequestIPPathStat,
    RequestIPProfile,
    UserGoal,
    UserGoalCompletion,
)

@admin.register(IntakeLog)
class IntakeLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'compound', 'amount', 'unit', 'taken_at', 'notes_preview']
    list_filter = ['compound', 'unit', 'taken_at', 'user']
    search_fields = ['user__username', 'compound__name', 'notes']
    date_hierarchy = 'taken_at'
    ordering = ['-taken_at']
    autocomplete_fields = ['compound']
    
    # Custom fields for the form
    fields = ['user', 'compound', 'amount', 'unit', 'taken_at', 'notes']
    
    # Make certain fields readonly for safety
    readonly_fields = []
    
    def notes_preview(self, obj):
        """Show a preview of notes in the list view"""
        if obj.notes:
            return obj.notes[:50] + ('...' if len(obj.notes) > 50 else '')
        return '-'
    notes_preview.short_description = 'Notes Preview'
    
    def get_queryset(self, request):
        """Optimize queryset with select_related to reduce database queries"""
        queryset = super().get_queryset(request)
        return queryset.select_related('user', 'compound')
    
    # Enable export actions
    actions = ['export_as_csv']
    
    def export_as_csv(self, request, queryset):
        """Export selected intake logs as CSV"""
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="intake_logs.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['User', 'Compound', 'Amount', 'Unit', 'Taken At', 'Notes'])
        
        for intake in queryset:
            writer.writerow([
                intake.user.username,
                intake.compound.name,
                intake.amount,
                intake.unit,
                intake.taken_at.strftime('%Y-%m-%d %H:%M:%S'),
                intake.notes
            ])
        
        return response
    export_as_csv.short_description = 'Export selected intake logs as CSV'


@admin.register(UserGoal)
class UserGoalAdmin(admin.ModelAdmin):
    list_display = ["user", "name", "goal_type", "is_active", "created_at"]
    list_filter = ["goal_type", "is_active", "created_at"]
    search_fields = ["user__username", "name"]
    autocomplete_fields = ["user"]
    ordering = ["-created_at"]


@admin.register(UserGoalCompletion)
class UserGoalCompletionAdmin(admin.ModelAdmin):
    list_display = ["goal", "date", "completed", "updated_at"]
    list_filter = ["completed", "date", "goal__goal_type"]
    search_fields = ["goal__user__username", "goal__name"]
    autocomplete_fields = ["goal"]
    ordering = ["-date", "-updated_at"]


@admin.register(RequestIPProfile)
class RequestIPProfileAdmin(admin.ModelAdmin):
    list_display = [
        "ip_address",
        "last_seen_at",
        "total_requests",
        "abuse_confidence_score",
        "abuse_usage_type",
        "abuse_country_code",
        "is_throttle_active",
        "throttle_limit_per_hour",
    ]
    list_filter = [
        "is_throttle_active",
        "abuse_country_code",
        "abuse_usage_type",
        "abuse_checked_at",
    ]
    search_fields = ["ip_address", "abuse_isp", "abuse_domain", "abuse_country_name"]
    ordering = ["-last_seen_at"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(RequestIPPathStat)
class RequestIPPathStatAdmin(admin.ModelAdmin):
    list_display = ["ip_profile", "method", "path", "request_count", "last_seen_at"]
    list_filter = ["method", "last_seen_at"]
    search_fields = ["ip_profile__ip_address", "path"]
    ordering = ["-request_count", "-last_seen_at"]
