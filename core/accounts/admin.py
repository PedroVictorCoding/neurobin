from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import UserProfile
from stacks.models import Stack

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name = 'Profile'
    verbose_name_plural = 'Profile'
    fields = ('profile_image', 'bio', 'location', 'website')

class StackInline(admin.TabularInline):
    model = Stack
    extra = 0
    fields = ('name', 'visibility', 'is_active', 'created')
    readonly_fields = ('created',)


class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline, StackInline)

# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('user__username', 'user__email', 'location', 'bio')
    readonly_fields = ('created_at', 'updated_at')
