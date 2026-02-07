from django.db import models
from django.conf import settings
from compounds.models import Compound

class IntakeLog(models.Model):
    TIME_OF_DAY_CHOICES = [
        ('morning', 'Morning'),
        ('afternoon', 'Afternoon'),
        ('night', 'Night'),
        ('pre-event', 'Pre-event'),
    ]
    UNIT_CHOICES = [
        ('mg', 'mg'),
        ('g', 'g'),
        ('mcg', 'mcg'),
        ('ml', 'ml'),
        ('drops', 'drops'),
        ('units', 'units'),
        ('other', 'Other'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    compound = models.ForeignKey(Compound, on_delete=models.CASCADE)
    stack_item = models.ForeignKey('stacks.StackItem', null=True, blank=True, on_delete=models.SET_NULL)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    amount = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=16, choices=UNIT_CHOICES, default='mg')
    time_of_day = models.CharField(max_length=10, choices=TIME_OF_DAY_CHOICES, default=None, blank=True, null=True)
    taken_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user} - {self.compound} @ {self.taken_at}"
