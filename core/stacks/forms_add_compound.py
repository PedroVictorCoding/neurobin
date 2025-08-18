from django import forms
from .models import StackItem
from compounds.models import Compound

class AddCompoundForm(forms.ModelForm):
    class Meta:
        model = StackItem
        fields = [
            'compound',
            'dosage_amount',
            'intake_time',
            'recurrence_interval',
            'recurrence_unit',
        ]
        widgets = {
            'compound': forms.Select(attrs={
                'class': 'form-select searchable',
                'style': 'max-width: 180px;'
            }),
            'dosage_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Dosage'
            }),
            'intake_time': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'recurrence_interval': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'style': 'width: 80px;'
            }),
            'recurrence_unit': forms.Select(attrs={
                'class': 'form-select',
                'style': 'max-width: 120px;'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['compound'].queryset = Compound.objects.all().order_by('name')
