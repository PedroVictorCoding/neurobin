from django.contrib import admin
from .models import Stack, StackItem, StackRiskAssessment

admin.site.register(Stack)
admin.site.register(StackItem)
admin.site.register(StackRiskAssessment)