from django.db import models
from django.conf import settings
from compounds.models import Compound

class IntakeLog(models.Model):
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
    amount = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=16, choices=UNIT_CHOICES, default='mg')
    taken_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user} - {self.compound} @ {self.taken_at}"
