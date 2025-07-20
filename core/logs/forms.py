from django import forms
from .models import IntakeLog

class IntakeLogForm(forms.ModelForm):
    class Meta:
        model = IntakeLog
        fields = ['compound', 'amount', 'unit', 'taken_at', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['compound'].widget.attrs.update({'class': 'form-select bg-dark text-light'})
        self.fields['amount'].widget.attrs.update({'class': 'form-control bg-dark text-light'})
        self.fields['unit'].widget.attrs.update({'class': 'form-select bg-dark text-light'})
        self.fields['taken_at'].widget.attrs.update({'class': 'form-control bg-dark text-light', 'type': 'datetime-local'})
        self.fields['notes'].widget.attrs.update({'class': 'form-control bg-dark text-light', 'rows': 3})