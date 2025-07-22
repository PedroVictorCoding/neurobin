from django import forms
from django.contrib.auth.models import User
from .models import (
    ResearchSnippet, 
    SnippetReview, 
    SnippetTag,
    ResearchSettings
)
from compounds.models import Compound


class ResearchSnippetForm(forms.ModelForm):
    """
    Form for creating and editing research snippets.
    """
    
    save_as_draft = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(),
        help_text="Save as draft instead of publishing"
    )
    
    class Meta:
        model = ResearchSnippet
        fields = [
            'title', 'content', 'compound', 'snippet_type', 
            'source_title', 'source_url', 'doi'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light',
                'placeholder': 'Brief descriptive title for your research snippet'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control bg-dark text-light',
                'rows': 8,
                'placeholder': 'Detailed research content, findings, or observations...'
            }),
            'compound': forms.Select(attrs={
                'class': 'form-select bg-dark text-light'
            }),
            'snippet_type': forms.Select(attrs={
                'class': 'form-select bg-dark text-light'
            }),
            'source_title': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light',
                'placeholder': 'Title of research paper, study, or source (optional)'
            }),
            'source_url': forms.URLInput(attrs={
                'class': 'form-control bg-dark text-light',
                'placeholder': 'https://pubmed.ncbi.nlm.nih.gov/...'
            }),
            'doi': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light',
                'placeholder': '10.1000/182'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Order compounds alphabetically
        self.fields['compound'].queryset = Compound.objects.all().order_by('name')


class SnippetReviewForm(forms.ModelForm):
    """
    Form for reviewing/voting on research snippets.
    """
    
    class Meta:
        model = SnippetReview
        fields = ['vote_type', 'comment']
        widgets = {
            'vote_type': forms.RadioSelect(attrs={
                'class': 'form-check-input'
            }),
            'comment': forms.Textarea(attrs={
                'class': 'form-control bg-dark text-light',
                'rows': 3,
                'placeholder': 'Optional: Provide feedback on the quality, accuracy, or usefulness of this snippet...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['comment'].required = False


class SnippetTagForm(forms.ModelForm):
    """
    Form for creating research snippet tags.
    """
    
    class Meta:
        model = SnippetTag
        fields = ['name', 'description', 'color']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light',
                'placeholder': 'Tag name (e.g., Dopaminergic, NMDA, Clinical Trial)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control bg-dark text-light',
                'rows': 3,
                'placeholder': 'Brief description of what this tag represents...'
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-light',
                'type': 'color',
            }),
        }


class SnippetSearchForm(forms.Form):
    """
    Form for searching and filtering research snippets.
    """
    
    query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-dark text-light',
            'placeholder': 'Search snippets by title, content, or source...'
        })
    )
    
    compound = forms.ModelChoiceField(
        queryset=Compound.objects.all().order_by('name'),
        required=False,
        empty_label="All compounds",
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )
    
    snippet_type = forms.ChoiceField(
        choices=[('', 'All types')] + ResearchSnippet.SNIPPET_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )
    
    status = forms.ChoiceField(
        choices=[('', 'All statuses')] + ResearchSnippet.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )
    
    tags = forms.ModelMultipleChoiceField(
        queryset=SnippetTag.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input'
        })
    )
    
    created_by = forms.ModelChoiceField(
        queryset=User.objects.filter(submitted_snippets__isnull=False).distinct().order_by('username'),
        required=False,
        empty_label="All authors",
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )
    
    ai_generated = forms.ChoiceField(
        choices=[('', 'All'), ('true', 'AI-Generated'), ('false', 'Human-Created')],
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )
    
    sort_by = forms.ChoiceField(
        choices=[
            ('-created_at', 'Newest First'),
            ('created_at', 'Oldest First'),
            ('-view_count', 'Most Viewed'),
            ('title', 'Title A-Z'),
            ('-title', 'Title Z-A'),
        ],
        initial='-created_at',
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )


class AIAnalysisForm(forms.Form):
    """
    Form for requesting AI analysis of research content.
    """
    
    content = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control bg-dark text-light',
            'rows': 10,
            'placeholder': 'Paste research abstract, paper excerpt, or text for AI analysis...'
        }),
        help_text="Paste text from a research paper, abstract, or other source for AI summarization and analysis."
    )
    
    analysis_type = forms.ChoiceField(
        choices=[
            ('summary', 'Generate Summary'),
            ('extract_findings', 'Extract Key Findings'),
            ('identify_mechanisms', 'Identify Mechanisms'),
            ('safety_assessment', 'Safety Assessment'),
            ('dosage_info', 'Dosage Information'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        }),
        help_text="What type of analysis would you like the AI to perform?"
    )
    
    target_compound = forms.ModelChoiceField(
        queryset=Compound.objects.all().order_by('name'),
        required=False,
        empty_label="Auto-detect compound",
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        }),
        help_text="Select the compound this research relates to, or leave blank for auto-detection."
    )


class ResearchSettingsForm(forms.ModelForm):
    """
    Admin form for configuring research system settings.
    """
    
    class Meta:
        model = ResearchSettings
        fields = [
            'public_submissions_enabled',
            'require_review_flair',
            'higher_confirmation_rate',
            'ai_summaries_enabled',
            'min_votes_for_flair',
            'verification_threshold',
            'flagging_threshold',
            'high_confidence_threshold',
        ]
        widgets = {
            'public_submissions_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'require_review_flair': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'higher_confirmation_rate': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'ai_summaries_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'min_votes_for_flair': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light',
                'min': 1
            }),
            'verification_threshold': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light',
                'min': 1
            }),
            'flagging_threshold': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light',
                'min': 1
            }),
            'high_confidence_threshold': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-light',
                'min': 1
            }),
        }


class BulkSnippetActionForm(forms.Form):
    """
    Form for performing bulk actions on multiple snippets (admin).
    """
    
    ACTION_CHOICES = [
        ('verify', 'Mark as Verified'),
        ('flag', 'Flag for Review'),
        ('reject', 'Reject'),
        ('delete', 'Delete'),
        ('change_visibility', 'Change Visibility'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        })
    )
    
    new_visibility = forms.ChoiceField(
        choices=ResearchSnippet.VISIBILITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select bg-dark text-light'
        }),
        help_text="Only used if action is 'Change Visibility'"
    )
    
    selected_snippets = forms.CharField(
        widget=forms.HiddenInput()
    )
