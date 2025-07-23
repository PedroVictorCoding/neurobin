from django.contrib import admin

from .models import *


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
