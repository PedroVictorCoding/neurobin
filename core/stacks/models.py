from django.db import models
from django.conf import settings
from compounds.models import Compound

class Stack(models.Model):
    VISIBILITY_CHOICES = [
        ('private', 'Private'),
        ('public', 'Public'),
        ('unlisted', 'Unlisted'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stacks')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    is_active = models.BooleanField(default=False)
    copied_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copies')
    copied_at = models.DateTimeField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class StackRiskAssessment(models.Model):
    RISK_LEVEL_CHOICES = [
        ('unknown', 'Unknown'),
        ('low', 'Low'),
        ('moderate', 'Moderate'),
        ('high', 'High'),
    ]

    stack = models.OneToOneField(
        Stack,
        on_delete=models.CASCADE,
        related_name='risk_assessment',
    )
    input_hash = models.CharField(max_length=64, db_index=True)
    compound_count = models.PositiveIntegerField(default=0)
    predicted_count = models.PositiveIntegerField(default=0)
    risk_score = models.FloatField(null=True, blank=True)
    risk_level = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='unknown')
    details = models.JSONField(default=dict, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-computed_at']

    def __str__(self):
        return f"Risk for {self.stack.name}: {self.risk_level}"


class StackItem(models.Model):
    DOSAGE_UNIT_CHOICES = [
        ('mg', 'mg'),
        ('g', 'g'),
        ('mcg', 'mcg'),
        ('ml', 'ml'),
        ('drops', 'drops'),
        ('units', 'units'),
        ('other', 'Other'),
    ]

    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name='items')
    compound = models.ForeignKey(Compound, on_delete=models.CASCADE)
    dosage_amount = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dosage_unit = models.CharField(max_length=16, choices=DOSAGE_UNIT_CHOICES, default='mg')
    TIME_OF_DAY_CHOICES = [
        ('morning', 'Morning'),
        ('afternoon', 'Afternoon'),
        ('night', 'Night'),
        ('pre-event', 'Pre-event'),
    ]
    time_of_day = models.CharField(max_length=10, choices=TIME_OF_DAY_CHOICES, default=None, blank=True, null=True)
    intake_time = models.DateTimeField(null=True, blank=True)
    # Recurrence settings
    RECURRENCE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    recurrence_interval = models.PositiveIntegerField(default=1)
    recurrence_unit = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, default='daily')
    order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    added = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'added']

    def __str__(self):
        return f"{self.compound.name} in {self.stack.name}"
