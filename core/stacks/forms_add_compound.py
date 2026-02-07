from django import forms
from .models import StackItem
from compounds.models import Compound

class AddCompoundForm(forms.ModelForm):
    compound = forms.ModelChoiceField(
        queryset=Compound.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select searchable',
            'style': 'max-width: 180px;'
        })
    )

    class Meta:
        model = StackItem
        fields = [
            'compound',
            'dosage_amount',
            'dosage_unit',
            'time_of_day',
            'intake_time',
            'recurrence_interval',
            'recurrence_unit',
            'notes',
        ]
        widgets = {
            'dosage_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Dosage'
            }),
            'dosage_unit': forms.Select(attrs={
                'class': 'form-select',
                'style': 'max-width: 110px;'
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
            'time_of_day': forms.Select(attrs={
                'class': 'form-select',
                'style': 'max-width: 160px;'
            }),
            'notes': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Notes (optional)',
                'style': 'min-width: 220px;'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This form is rendered many times on the stacks page. Loading all compounds
        # into the <select> is slow and generates huge HTML. Select2 (initialized in
        # base.html) fetches options via AJAX. We only include the currently selected
        # compound (when bound) so validation works without preloading everything.
        compound_value = None
        if self.is_bound:
            compound_value = self.data.get(self.add_prefix('compound'))
        elif getattr(self.instance, 'compound_id', None):
            compound_value = self.instance.compound_id
        elif self.initial.get('compound'):
            compound_value = getattr(self.initial.get('compound'), 'pk', self.initial.get('compound'))

        if compound_value:
            try:
                compound_id = int(compound_value)
            except (TypeError, ValueError):
                compound_id = None
            if compound_id:
                self.fields['compound'].queryset = Compound.objects.filter(id=compound_id)
