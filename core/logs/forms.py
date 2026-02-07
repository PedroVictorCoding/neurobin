from django import forms
from .models import IntakeLog
from compounds.models import Compound

class IntakeLogForm(forms.ModelForm):
    # Custom compound field that will be a text input with autocomplete
    compound_search = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-dark text-light',
            'placeholder': 'Search for a compound...',
            'autocomplete': 'off'
        })
    )
    
    class Meta:
        model = IntakeLog
        fields = ['compound', 'amount', 'unit', 'time_of_day', 'taken_at', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hide the original compound field since we'll use compound_search
        self.fields['compound'].widget = forms.HiddenInput()
        self.fields['amount'].widget.attrs.update({'class': 'form-control bg-dark text-light'})
        self.fields['unit'].widget.attrs.update({'class': 'form-select bg-dark text-light'})
        self.fields['time_of_day'].widget.attrs.update({'class': 'form-select bg-dark text-light'})
        self.fields['taken_at'].widget.attrs.update({'class': 'form-control bg-dark text-light', 'type': 'datetime-local'})
        self.fields['notes'].widget.attrs.update({'class': 'form-control bg-dark text-light', 'rows': 3})
        
        # If form has existing data, populate the search field
        if self.instance and self.instance.compound_id:
            self.fields['compound_search'].initial = self.instance.compound.name
    
    def clean(self):
        cleaned_data = super().clean()
        compound_search = cleaned_data.get('compound_search')
        compound = cleaned_data.get('compound')
        
        if compound_search and not compound:
            # Try to find the compound by exact name match first
            try:
                compound = Compound.objects.get(name__iexact=compound_search)
                cleaned_data['compound'] = compound
            except Compound.DoesNotExist:
                # Try to find by alias match
                try:
                    compound = Compound.objects.filter(aliases__icontains=compound_search).first()
                    if compound:
                        cleaned_data['compound'] = compound
                    else:
                        raise forms.ValidationError('Please select a valid compound from the search results.')
                except Exception:
                    raise forms.ValidationError('Please select a valid compound from the search results.')
        
        return cleaned_data
