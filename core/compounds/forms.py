from django import forms
from .models import Compound


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