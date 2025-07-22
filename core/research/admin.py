from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    ResearchSnippet,
    SnippetReview,
    SnippetTag,
    SnippetTagging,
    UserRole,
    ResearchSettings
)


@admin.register(ResearchSnippet)
class ResearchSnippetAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'compound', 'snippet_type', 'status', 
        'visibility', 'confidence_level_display', 'created_by', 'view_count', 'created_at'
    )
    list_filter = (
        'status', 'visibility', 'snippet_type', 'ai_generated',
        'created_at', 'compound'
    )
    search_fields = (
        'title', 'content', 'source_title', 'created_by__username',
        'compound__name'
    )
    readonly_fields = ('view_count', 'created_at', 'updated_at', 'net_score_display', 'confidence_level_display')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'content', 'compound', 'snippet_type')
        }),
        ('Visibility & Status', {
            'fields': ('visibility', 'status', 'created_by')
        }),
        ('Source Information', {
            'fields': ('source_title', 'source_url', 'doi'),
            'classes': ('collapse',)
        }),
        ('AI & Review Data', {
            'fields': ('ai_summary', 'ai_generated'),
            'classes': ('collapse',)
        }),
        ('Analytics', {
            'fields': ('view_count', 'created_at', 'updated_at', 'net_score_display'),
            'classes': ('collapse',)
        }),
    )
    
    def net_score_display(self, obj):
        """Display review statistics."""
        scores = obj.net_score
        positive = scores.get('positive', 0)
        negative = scores.get('negative', 0)
        net = positive - negative
        
        color = 'green' if net > 0 else 'red' if net < 0 else 'gray'
        return format_html(
            '<span style="color: {};">+{} / -{} (Net: {})</span>',
            color, positive, negative, net
        )
    net_score_display.short_description = 'Review Score'
    
    def confidence_level_display(self, obj):
        """Display confidence level with color coding."""
        level = obj.confidence_level
        color_map = {
            'High': 'green',
            'Medium': 'orange',
            'Low/None': 'red',
            'Unknown': 'gray'
        }
        color = color_map.get(level, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, level
        )
    confidence_level_display.short_description = 'Confidence'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'compound', 'created_by'
        ).prefetch_related('reviews', 'tags')


@admin.register(SnippetReview)
class SnippetReviewAdmin(admin.ModelAdmin):
    list_display = (
        'snippet_title', 'reviewer', 'vote_type', 
        'created_at', 'has_comment'
    )
    list_filter = ('vote_type', 'created_at')
    search_fields = (
        'snippet__title', 'reviewer__username', 'comment'
    )
    readonly_fields = ('created_at',)
    
    def snippet_title(self, obj):
        return obj.snippet.title[:50] + ('...' if len(obj.snippet.title) > 50 else '')
    snippet_title.short_description = 'Snippet'
    
    def has_comment(self, obj):
        return bool(obj.comment)
    has_comment.boolean = True
    has_comment.short_description = 'Has Comment'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'snippet', 'reviewer'
        )


@admin.register(SnippetTag)
class SnippetTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color_display', 'snippet_count', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'snippet_count')
    
    def color_display(self, obj):
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 3px;">{}</span>',
            obj.color, obj.name
        )
    color_display.short_description = 'Color Preview'
    
    def snippet_count(self, obj):
        return obj.snippets.count()
    snippet_count.short_description = 'Snippet Count'


@admin.register(SnippetTagging)
class SnippetTaggingAdmin(admin.ModelAdmin):
    list_display = ('snippet', 'tag', 'tagged_by', 'created_at')
    list_filter = ('tag', 'created_at')
    search_fields = ('snippet__title', 'tag__name', 'tagged_by__username')
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'snippet', 'tag', 'tagged_by'
        )


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'role', 'vote_weight', 'can_moderate', 'created_at'
    )
    list_filter = ('role', 'can_moderate', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at',)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(ResearchSettings)
class ResearchSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'settings_summary', 'updated_at'
    )
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Feature Toggles', {
            'fields': (
                'public_submissions_enabled',
                'require_review_flair',
                'higher_confirmation_rate',
                'ai_summaries_enabled'
            )
        }),
        ('Review Thresholds', {
            'fields': (
                'min_votes_for_flair',
                'verification_threshold',
                'flagging_threshold',
                'high_confidence_threshold'
            )
        }),
        ('System Info', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def settings_summary(self, obj):
        enabled_features = []
        if obj.public_submissions_enabled:
            enabled_features.append('Public Submissions')
        if obj.require_review_flair:
            enabled_features.append('Review Flair')
        if obj.ai_summaries_enabled:
            enabled_features.append('AI Summaries')
        
        return f"Enabled: {', '.join(enabled_features) if enabled_features else 'None'}"
    settings_summary.short_description = 'Active Features'
    
    def has_add_permission(self, request):
        # Only allow one settings instance
        return not ResearchSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion of settings
        return False


# Custom admin site configuration
admin.site.site_header = "Neurobin Research Administration"
admin.site.site_title = "Research Admin"
admin.site.index_title = "Research Snippet System Management"
