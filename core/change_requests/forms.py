from django import forms
from django.contrib.contenttypes.models import ContentType
from .models import ChangeRequest, ChangeRequestComment
import json


class CompoundChangeRequestForm(forms.ModelForm):
    # Compound specific fields
    name = forms.CharField(max_length=200, required=False)
    compound_description = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), required=False)
    categories = forms.CharField(widget=forms.HiddenInput(), required=False)
    
    class Meta:
        model = ChangeRequest
        fields = ['title', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief description of changes'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Additional notes (optional)'}),
        }
    
    def __init__(self, *args, compound=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.compound = compound
        
        if compound:
            # Pre-fill with current compound data
            self.fields['name'].initial = compound.name
            self.fields['compound_description'].initial = compound.description or ''
            
            # Set categories as comma-separated IDs
            category_ids = list(compound.categories.values_list('id', flat=True))
            self.fields['categories'].initial = ','.join(map(str, category_ids))
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Ensure at least one field is being changed
        if self.compound:
            changes_detected = False
            
            if cleaned_data.get('name') != self.compound.name:
                changes_detected = True
            
            if cleaned_data.get('compound_description') != (self.compound.description or ''):
                changes_detected = True
            
            # Check categories
            current_category_ids = set(self.compound.categories.values_list('id', flat=True))
            new_category_ids = set()
            if cleaned_data.get('categories'):
                try:
                    new_category_ids = set(map(int, cleaned_data['categories'].split(',')))
                except ValueError:
                    pass
            
            if current_category_ids != new_category_ids:
                changes_detected = True
            
            if not changes_detected:
                raise forms.ValidationError("No changes detected. Please modify at least one field.")
        
        return cleaned_data
    
    def get_changes_data(self):
        """Generate the changes_data JSON for the ChangeRequest"""
        if not self.compound:
            return {}
        
        changes = {}
        
        # Check name changes
        new_name = self.cleaned_data.get('name', '').strip()
        if new_name != self.compound.name:
            changes['name'] = {
                'before': self.compound.name,
                'after': new_name
            }
        
        # Check description changes
        new_desc = self.cleaned_data.get('compound_description', '').strip()
        current_desc = self.compound.description or ''
        if new_desc != current_desc:
            changes['description'] = {
                'before': current_desc,
                'after': new_desc
            }
        
        # Check category changes
        current_category_ids = list(self.compound.categories.values_list('id', flat=True))
        new_category_ids = []
        if self.cleaned_data.get('categories'):
            try:
                new_category_ids = list(map(int, self.cleaned_data['categories'].split(',')))
            except ValueError:
                pass
        
        if set(current_category_ids) != set(new_category_ids):
            # Get category names for display
            from compounds.models import CompoundCategories
            current_names = list(CompoundCategories.objects.filter(id__in=current_category_ids).values_list('name', flat=True))
            new_names = list(CompoundCategories.objects.filter(id__in=new_category_ids).values_list('name', flat=True))
            
            changes['categories'] = {
                'before': current_names,
                'after': new_names,
                'before_ids': current_category_ids,
                'after_ids': new_category_ids
            }
        
        return changes


class ChangeRequestCommentForm(forms.ModelForm):
    class Meta:
        model = ChangeRequestComment
        fields = ['comment']
        widgets = {
            'comment': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Add a comment...'
            }),
        }


class ReviewChangeRequestForm(forms.Form):
    STATUS_CHOICES = [
        ('approved', 'Approve'),
        ('rejected', 'Reject'),
    ]
    
    action = forms.ChoiceField(choices=STATUS_CHOICES, widget=forms.RadioSelect)
    review_notes = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False,
        help_text="Optional notes about your decision"
    )
