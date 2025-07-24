from django.contrib import admin
from .models import IntakeLog

@admin.register(IntakeLog)
class IntakeLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'compound', 'amount', 'unit', 'taken_at', 'notes_preview']
    list_filter = ['compound', 'unit', 'taken_at', 'user']
    search_fields = ['user__username', 'compound__name', 'notes']
    date_hierarchy = 'taken_at'
    ordering = ['-taken_at']
    
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
