from django.db import models
from django.conf import settings
from compounds.models import Compound

class Stack(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stacks')
    name = models.CharField(max_length=100)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"

class StackItem(models.Model):
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name='items')
    compound = models.ForeignKey(Compound, on_delete=models.CASCADE)
    dosage_amount = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
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
