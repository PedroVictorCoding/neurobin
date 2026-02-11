from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone
import json


class ChangeRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('applied', 'Applied'),
    ]
    
    # Basic request info
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # User who made the request
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='change_requests')
    
    # Auto-approve for staff/superuser
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Generic foreign key to any model (Compound, Research, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # JSON field to store the changes (before/after values)
    changes_data = models.JSONField(help_text="JSON containing before/after field values")
    
    # Approval info
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='reviewed_change_requests')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    
    # Applied info
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='applied_change_requests')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Change Request'
        verbose_name_plural = 'Change Requests'
    
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"
    
    @property
    def is_auto_approved(self):
        """Check if this request should be auto-approved"""
        return self.requested_by.is_staff or self.requested_by.is_superuser
    
    def get_before_after_diff(self):
        """Return formatted before/after comparison"""
        if not self.changes_data:
            return {}
        
        diff = {}
        for field, values in self.changes_data.items():
            diff[field] = {
                'before': values.get('before', ''),
                'after': values.get('after', ''),
                'changed': values.get('before') != values.get('after')
            }
        return diff
    
    def apply_changes(self, applied_by_user):
        """Apply the changes to the target object"""
        if self.status not in ['approved'] and not self.is_auto_approved:
            raise ValueError("Cannot apply unapproved changes")
        
        obj = self.content_object
        if not obj:
            raise ValueError("Target object not found")
        
        # Apply each field change
        for field_name, values in self.changes_data.items():
            if hasattr(obj, field_name):
                setattr(obj, field_name, values.get('after'))
        
        obj.save()
        
        # Update status
        self.status = 'applied'
        self.applied_at = timezone.now()
        self.applied_by = applied_by_user
        self.save()


class ChangeRequestComment(models.Model):
    change_request = models.ForeignKey(ChangeRequest, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"Comment by {self.user.username} on {self.change_request.title}"


class AppliedChange(models.Model):
    """Track history of applied changes for audit trail"""
    change_request = models.OneToOneField(ChangeRequest, on_delete=models.CASCADE)
    
    # Store snapshot of object before change
    before_data = models.JSONField()
    after_data = models.JSONField()
    
    # Track who applied it
    applied_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-applied_at']
        verbose_name = 'Applied Change'
        verbose_name_plural = 'Applied Changes'
    
    def __str__(self):
        return f"Applied: {self.change_request.title}"


class FeatureRequest(models.Model):
    REQUEST_TYPE_CHOICES = [
        ('feature', 'Feature Request'),
        ('consideration', 'Consideration'),
    ]
    STATUS_CHOICES = [
        ('new', 'New'),
        ('reviewed', 'Reviewed'),
        ('planned', 'Planned'),
        ('done', 'Done'),
        ('rejected', 'Rejected'),
    ]

    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, default='feature')
    title = models.CharField(max_length=200)
    details = models.TextField()
    display_name = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='feature_requests',
    )
    source_page = models.CharField(max_length=255, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Feature Request'
        verbose_name_plural = 'Feature Requests'

    def __str__(self):
        return f"[{self.request_type}] {self.title}"
