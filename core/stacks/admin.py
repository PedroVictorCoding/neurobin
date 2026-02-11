from django.contrib import admin
from .models import (
    MechanismTraitRule,
    Stack,
    StackDangerousPairRule,
    StackItem,
    StackRiskAssessment,
    StackTrait,
)

admin.site.register(Stack)
admin.site.register(StackItem)
admin.site.register(StackRiskAssessment)
admin.site.register(StackTrait)
admin.site.register(MechanismTraitRule)
admin.site.register(StackDangerousPairRule)
