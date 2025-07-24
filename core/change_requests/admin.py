from django.contrib import admin
from .models import ChangeRequest, ChangeRequestComment, AppliedChange


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ['title', 'requested_by', 'status', 'content_object', 'created_at', 'reviewed_by']
    list_filter = ['status', 'created_at', 'content_type']
    search_fields = ['title', 'description', 'requested_by__username']
    readonly_fields = ['created_at', 'updated_at', 'applied_at']
    
    fieldsets = (
        ('Request Info', {
            'fields': ('title', 'description', 'requested_by', 'content_type', 'object_id')
        }),
        ('Changes', {
            'fields': ('changes_data',)
        }),
        ('Status', {
            'fields': ('status', 'reviewed_by', 'reviewed_at', 'review_notes')
        }),
        ('Application', {
            'fields': ('applied_by', 'applied_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ChangeRequestComment)
class ChangeRequestCommentAdmin(admin.ModelAdmin):
    list_display = ['change_request', 'user', 'created_at']
    list_filter = ['created_at']
    search_fields = ['comment', 'user__username', 'change_request__title']


@admin.register(AppliedChange)
class AppliedChangeAdmin(admin.ModelAdmin):
    list_display = ['change_request', 'applied_by', 'applied_at']
    list_filter = ['applied_at']
    readonly_fields = ['applied_at']
    search_fields = ['change_request__title', 'applied_by__username']
