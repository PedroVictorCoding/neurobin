from django.contrib import admin

from .models import (
    Compound, 
    CompoundCategories, 
    Target, 
    CompoundMechanismOfAction, 
    CompoundRating, 
    CompoundSafetyScreening,
    EffectWindow
)


@admin.register(Compound)
class CompoundAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'smiles')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('categories',)
    fields = ('name', 'slug', 'description', 'aliases', 'smiles', 'categories', 'mechanism_of_action')

@admin.register(CompoundCategories)
class CompoundCategoriesAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

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

@admin.register(CompoundSafetyScreening)
class CompoundSafetyScreeningAdmin(admin.ModelAdmin):
    list_display = ('compound', 'created_by', 'confidence_score', 'created_at')
    list_filter = ('confidence_score',)
    search_fields = ('compound__name', 'user__username')


@admin.register(EffectWindow)
class EffectWindowAdmin(admin.ModelAdmin):
    list_display = ('compound', 'effect_shape', 'onset_minutes', 'peak_min_minutes', 'peak_max_minutes', 'duration_minutes', 'created_by')
    list_filter = ('effect_shape', 'created_by')
    search_fields = ('compound__name', 'notes')
    readonly_fields = ('created_at',)
    
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
