from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count, Avg
from .models import ScoringCategory, CompoundScore, ModelTrainingLog, UserCompoundAnnotation


@admin.register(ScoringCategory)
class ScoringCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'compound_count', 'avg_score', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['created_at', 'updated_at']

    def compound_count(self, obj):
        return obj.get_compound_count()
    compound_count.short_description = 'Compounds Scored'
    compound_count.admin_order_field = 'compound_count'

    def avg_score(self, obj):
        avg = CompoundScore.objects.filter(category=obj).aggregate(Avg('score'))['score__avg']
        if avg:
            return f"{avg:.3f}"
        return "-"
    avg_score.short_description = 'Avg Score'

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            compound_count=Count('compoundscore')
        )
        return queryset


class CompoundScoreInline(admin.TabularInline):
    model = CompoundScore
    extra = 0
    readonly_fields = ['timestamp', 'updated_at', 'rank_display']
    fields = ['category', 'score', 'confidence', 'model_version', 'rank_display', 'timestamp']

    def rank_display(self, obj):
        if obj.pk:
            return f"#{obj.rank_in_category}"
        return "-"
    rank_display.short_description = 'Rank'


@admin.register(CompoundScore)
class CompoundScoreAdmin(admin.ModelAdmin):
    list_display = ['compound_link', 'category', 'score_bar', 'confidence_bar', 'rank_display', 'model_version', 'timestamp']
    list_filter = ['category', 'model_version', 'timestamp']
    search_fields = ['compound__name', 'compound__chembl_id']
    readonly_fields = ['timestamp', 'updated_at', 'rank_display', 'score_percentage', 'confidence_percentage']
    list_per_page = 50
    date_hierarchy = 'timestamp'

    fieldsets = (
        ('Basic Information', {
            'fields': ('compound', 'category', 'score', 'confidence')
        }),
        ('Model Information', {
            'fields': ('model_version', 'features_used')
        }),
        ('Metadata', {
            'fields': ('rank_display', 'score_percentage', 'confidence_percentage', 'timestamp', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def compound_link(self, obj):
        url = reverse('admin:compounds_compound_change', args=[obj.compound.pk])
        return format_html('<a href="{}">{}</a>', url, obj.compound.name)
    compound_link.short_description = 'Compound'
    compound_link.admin_order_field = 'compound__name'

    def score_bar(self, obj):
        percentage = obj.score_percentage
        color = 'green' if percentage > 70 else 'orange' if percentage > 40 else 'red'
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: {}; height: 20px; border-radius: 3px; text-align: center; color: white; line-height: 20px; font-size: 12px;">'
            '{}%</div></div>',
            percentage, color, percentage
        )
    score_bar.short_description = 'Score'
    score_bar.admin_order_field = 'score'

    def confidence_bar(self, obj):
        percentage = obj.confidence_percentage
        color = 'blue' if percentage > 80 else 'purple' if percentage > 60 else 'gray'
        return format_html(
            '<div style="width: 80px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: {}; height: 15px; border-radius: 3px; text-align: center; color: white; line-height: 15px; font-size: 11px;">'
            '{}%</div></div>',
            percentage, color, percentage
        )
    confidence_bar.short_description = 'Confidence'
    confidence_bar.admin_order_field = 'confidence'

    def rank_display(self, obj):
        if obj.pk:
            rank = obj.rank_in_category
            return format_html('<strong>#{}</strong>', rank)
        return "-"
    rank_display.short_description = 'Rank'


@admin.register(ModelTrainingLog)
class ModelTrainingLogAdmin(admin.ModelAdmin):
    list_display = ['category', 'model_version', 'status', 'training_samples', 'validation_accuracy', 'training_duration', 'trained_by']
    list_filter = ['status', 'category', 'training_started']
    search_fields = ['model_version', 'category__name']
    readonly_fields = ['training_started', 'training_completed', 'training_duration']
    date_hierarchy = 'training_started'

    fieldsets = (
        ('Training Information', {
            'fields': ('category', 'model_version', 'status', 'trained_by')
        }),
        ('Training Metrics', {
            'fields': ('training_samples', 'validation_accuracy', 'validation_loss', 'hyperparameters')
        }),
        ('Timing', {
            'fields': ('training_started', 'training_completed', 'training_duration')
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )

    def training_duration(self, obj):
        if obj.training_completed and obj.training_started:
            duration = obj.training_completed - obj.training_started
            total_seconds = int(duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return "-"
    training_duration.short_description = 'Duration'


@admin.register(UserCompoundAnnotation)
class UserCompoundAnnotationAdmin(admin.ModelAdmin):
    list_display = ['compound', 'category', 'user', 'user_score', 'is_verified', 'created_at']
    list_filter = ['category', 'is_verified', 'created_at', 'user']
    search_fields = ['compound__name', 'user__username', 'notes']
    readonly_fields = ['created_at']
    list_editable = ['is_verified']

    fieldsets = (
        ('Annotation Information', {
            'fields': ('compound', 'category', 'user', 'user_score', 'is_verified')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Metadata', {
            'fields': ('created_at',)
        }),
    )
