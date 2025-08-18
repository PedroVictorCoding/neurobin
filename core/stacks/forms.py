from django import forms
from .models import Stack

class StackForm(forms.ModelForm):
    class Meta:
        model = Stack
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Stack name'})
        }
