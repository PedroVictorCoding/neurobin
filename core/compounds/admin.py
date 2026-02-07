from django.contrib import admin

from .models import (
    Compound, 
    CompoundADMETPrediction,
    CompoundMolPropPrediction,
    CompoundCategories, 
    Target, 
    CompoundMechanismOfAction, 
    CompoundRating, 
    CompoundSafetyScreening,
    EffectWindow,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    ActionType,
    TargetType
)
from research.models import ResearchImportJob


@admin.register(Compound)
class CompoundAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'chembl_id', 'smiles')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('categories',)
    search_fields = ('name', 'aliases', 'description', 'chembl_id')
    fields = ('name', 'slug', 'chembl_id', 'description', 'aliases', 'smiles', 'categories', 'mechanism_of_action')
    actions = ['queue_research_import']

    def queue_research_import(self, request, queryset):
        created = 0
        skipped = 0
        for compound in queryset:
            existing = ResearchImportJob.objects.filter(
                compound=compound,
                status__in=['queued', 'running'],
            ).exists()
            if existing:
                skipped += 1
                continue
            ResearchImportJob.objects.create(
                compound=compound,
                requested_by=request.user,
                status='queued',
                max_results=10,
            )
            created += 1
        if created:
            self.message_user(request, f"Queued {created} research import job(s).")
        if skipped:
            self.message_user(request, f"Skipped {skipped} compound(s) with existing queued/running jobs.")
    queue_research_import.short_description = "Queue research import for selected compounds"

@admin.register(CompoundADMETPrediction)
class CompoundADMETPredictionAdmin(admin.ModelAdmin):
    list_display = ('compound', 'computed_at', 'model_version')
    search_fields = ('compound__name', 'compound__slug')
    autocomplete_fields = ('compound',)
    readonly_fields = ('computed_at',)


@admin.register(CompoundMolPropPrediction)
class CompoundMolPropPredictionAdmin(admin.ModelAdmin):
    list_display = ('compound', 'computed_at', 'model_version')
    search_fields = ('compound__name', 'compound__slug')
    autocomplete_fields = ('compound',)
    readonly_fields = ('computed_at',)

@admin.register(CompoundCategories)
class CompoundCategoriesAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_type', 'chembl_id', 'organism')
    search_fields = ('name', 'description', 'chembl_id')
    list_filter = ('target_type',)

@admin.register(CompoundMechanismOfAction)
class CompoundMechanismOfActionAdmin(admin.ModelAdmin):
    list_display = ('target_name', 'target_type', 'target_interaction')
    search_fields = ('target_name',)
    list_filter = ('target_type', 'target_interaction')

@admin.register(CompoundRating)
class CompoundRatingAdmin(admin.ModelAdmin):
    list_display = ('compound', 'user', 'score', 'created_at')
    list_filter = ('score',)
    search_fields = ('compound__name', 'user__username')
    autocomplete_fields = ['compound']

@admin.register(CompoundSafetyScreening)
class CompoundSafetyScreeningAdmin(admin.ModelAdmin):
    list_display = ('compound', 'created_by', 'confidence_score', 'created_at')
    list_filter = ('confidence_score',)
    search_fields = ('compound__name', 'user__username')
    autocomplete_fields = ['compound']


@admin.register(EffectWindow)
class EffectWindowAdmin(admin.ModelAdmin):
    list_display = ('compound', 'effect_shape', 'onset_minutes', 'peak_min_minutes', 'peak_max_minutes', 'duration_minutes', 'created_by')
    list_filter = ('effect_shape', 'created_by')
    search_fields = ('compound__name', 'notes')
    readonly_fields = ('created_at',)
    autocomplete_fields = ['compound']
    fieldsets = (
        ('Basic Information', {
            'fields': ('compound', 'effect_shape', 'notes')
        }),
        ('Timing Parameters (minutes)', {
            'fields': ('onset_minutes', 'peak_min_minutes', 'peak_max_minutes', 'duration_minutes', 'half_life_minutes')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at')
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(CompoundTargetInteraction)
class CompoundTargetInteractionAdmin(admin.ModelAdmin):
    list_display = ('compound', 'target', 'mechanism', 'affinity_level', 'source')
    list_filter = ('mechanism', 'affinity_level', 'source', 'target__target_type')
    search_fields = ('compound__name', 'target__name', 'notes')
    autocomplete_fields = ('compound', 'target')
    
    fieldsets = (
        ('Interaction Details', {
            'fields': ('compound', 'target', 'mechanism', 'affinity_level')
        }),
        ('Additional Information', {
            'fields': ('notes', 'source')
        })
    )


@admin.register(CompoundToCompoundTargetInteraction)
class CompoundToCompoundTargetInteractionAdmin(admin.ModelAdmin):
    list_display = ('compound_a', 'compound_b', 'target', 'interaction_type', 'confidence')
    list_filter = ('interaction_type', 'confidence', 'target__target_type', 'created_at')
    search_fields = ('compound_a__name', 'compound_b__name', 'target__name', 'description')
    autocomplete_fields = ('compound_a', 'compound_b', 'target')
    readonly_fields = ('created_at',)
    autocomplete_fields = ['compound_a', 'compound_b', 'target']
    
    fieldsets = (
        ('Compounds and Target', {
            'fields': ('compound_a', 'compound_b', 'target')
        }),
        ('Interaction Details', {
            'fields': ('interaction_type', 'description', 'confidence')
        }),
        ('Source and Metadata', {
            'fields': ('source', 'created_by', 'created_at')
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('compound_a', 'compound_b', 'target')


@admin.register(ActionType)
class ActionTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name', 'category', 'description')
    search_fields = ('name', 'display_name', 'description', 'category')
    list_filter = ('category',)
    ordering = ('name',)


@admin.register(TargetType)
class TargetTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name', 'category', 'description')
    search_fields = ('name', 'display_name', 'description', 'category')
    list_filter = ('category',)
    ordering = ('name',)
