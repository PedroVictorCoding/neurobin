from django import forms
from .models import Compound, CompoundMechanismOfAction, CompoundCategories, Target


class CompoundForm(forms.ModelForm):
    class Meta:
        model = Compound
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if widget.__class__.__name__ in ['CheckboxSelectMultiple', 'CheckboxInput']:
                widget.attrs['class'] = 'form-check-input'
            else:
                widget.attrs['class'] = 'form-control bg-dark text-light'


class MechanismOfActionForm(forms.ModelForm):
    class Meta:
        model = CompoundMechanismOfAction
        fields = ['description', 'target_name', 'target_type', 'target_interaction']
        widgets = {
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Mechanism description'}),
            'target_name': forms.Select(attrs={'class': 'form-control'}),
            'target_type': forms.Select(attrs={'class': 'form-control'}),
            'target_interaction': forms.Select(attrs={'class': 'form-control'}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = CompoundCategories
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Category description'}),
        }


class TargetForm(forms.ModelForm):
    class Meta:
        model = Target
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Target name (e.g., GABA-A receptor)'}),
        }
