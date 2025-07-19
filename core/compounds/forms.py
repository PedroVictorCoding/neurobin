from django import forms
from .models import Compound, CompoundCategories


class CompoundForm(forms.ModelForm):
    class Meta:
        model = Compound
        fields = [
            'name',
            'description',
            'aliases',
            'categories',
            'mechanism_of_action',
            'receptor_targets',
        ]
        widgets = {
            'categories': forms.CheckboxSelectMultiple,
            'mechanism_of_action': forms.CheckboxSelectMultiple,
            'receptor_targets': forms.CheckboxSelectMultiple,
        }