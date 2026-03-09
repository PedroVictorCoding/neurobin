from django.contrib import admin
from .models import (
    CompoundTaxonomyTag,
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


@admin.register(CompoundTaxonomyTag)
class CompoundTaxonomyTagAdmin(admin.ModelAdmin):
    list_display  = ('compound', 'group_label', 'sub_label', 'group_id', 'sub_id')
    list_filter   = ('group_id',)
    search_fields = ('compound__name', 'group_label', 'sub_label', 'sub_id')
    ordering      = ('compound__name', 'group_id', 'sub_id')
