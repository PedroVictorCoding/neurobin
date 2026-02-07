from django.db import models
from django.conf import settings


class Stack(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class StackItem(models.Model):
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name='items')
    compound_name = models.CharField(max_length=200)
    dosage_amount = models.CharField(max_length=50, blank=True)
    intake_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.compound_name} ({self.dosage_amount})"
