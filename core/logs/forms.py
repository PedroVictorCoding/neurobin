from django import forms
from django.utils import timezone

from compounds.models import Compound

from .models import BloodworkEntry, IntakeLog


class IntakeLogForm(forms.ModelForm):
    # Custom compound field that will be a text input with autocomplete
    compound_search = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control bg-dark text-light",
                "placeholder": "Search for a compound...",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = IntakeLog
        fields = ["compound", "amount", "unit", "time_of_day", "taken_at", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hide the original compound field since we'll use compound_search
        self.fields["compound"].widget = forms.HiddenInput()
        self.fields["amount"].widget.attrs.update({"class": "form-control bg-dark text-light"})
        self.fields["unit"].widget.attrs.update({"class": "form-select bg-dark text-light"})
        self.fields["time_of_day"].widget.attrs.update({"class": "form-select bg-dark text-light"})
        self.fields["taken_at"].widget.attrs.update(
            {"class": "form-control bg-dark text-light", "type": "datetime-local"}
        )
        self.fields["notes"].widget.attrs.update(
            {"class": "form-control bg-dark text-light", "rows": 3}
        )

        # If form has existing data, populate the search field
        if self.instance and self.instance.compound_id:
            self.fields["compound_search"].initial = self.instance.compound.name

    def clean(self):
        cleaned_data = super().clean()
        compound_search = cleaned_data.get("compound_search")
        compound = cleaned_data.get("compound")

        if compound_search and not compound:
            # Try to find the compound by exact name match first
            try:
                compound = Compound.objects.get(name__iexact=compound_search)
                cleaned_data["compound"] = compound
            except Compound.DoesNotExist:
                # Try to find by alias match
                try:
                    compound = Compound.objects.filter(aliases__icontains=compound_search).first()
                    if compound:
                        cleaned_data["compound"] = compound
                    else:
                        raise forms.ValidationError(
                            "Please select a valid compound from the search results."
                        )
                except Exception:
                    raise forms.ValidationError(
                        "Please select a valid compound from the search results."
                    )

        return cleaned_data


class RelatedIntakeLogMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        taken_at = timezone.localtime(obj.taken_at).strftime("%b %d, %Y %H:%M")
        amount_bits = []
        if obj.amount:
            amount_bits.append(obj.amount)
        if obj.unit:
            amount_bits.append(obj.unit)
        amount_display = f" ({' '.join(amount_bits)})" if amount_bits else ""
        return f"{taken_at} | {obj.compound.name}{amount_display}"


class BloodworkEntryForm(forms.ModelForm):
    related_intake_logs = RelatedIntakeLogMultipleChoiceField(
        queryset=IntakeLog.objects.none(),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select bg-dark text-light border-secondary",
                "size": 8,
            }
        ),
        help_text="Optional: link intake events that may explain this panel.",
    )

    class Meta:
        model = BloodworkEntry
        fields = ["collected_at", "panel_name", "lab_name", "notes"]
        widgets = {
            "collected_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control bg-dark text-light border-secondary",
                    "type": "datetime-local",
                }
            ),
            "panel_name": forms.TextInput(
                attrs={
                    "class": "form-control bg-dark text-light border-secondary",
                    "placeholder": "Comprehensive Metabolic Panel",
                }
            ),
            "lab_name": forms.TextInput(
                attrs={
                    "class": "form-control bg-dark text-light border-secondary",
                    "placeholder": "Quest Diagnostics",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control bg-dark text-light border-secondary",
                    "rows": 3,
                    "placeholder": "Context, symptoms, fasting status, time since last dose...",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and getattr(user, "is_authenticated", False):
            self.fields["related_intake_logs"].queryset = (
                IntakeLog.objects.filter(user=user)
                .select_related("compound")
                .order_by("-taken_at")
            )


class BloodworkMeasurementForm(forms.Form):
    marker_name = forms.CharField(
        required=False,
        max_length=160,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
                "placeholder": "LDL",
            }
        ),
    )
    value = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
                "placeholder": "112",
                "step": "0.001",
            }
        ),
    )
    unit = forms.CharField(
        required=False,
        max_length=60,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
                "placeholder": "mg/dL",
            }
        ),
    )
    reference_low = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
                "placeholder": "40",
                "step": "0.001",
            }
        ),
    )
    reference_high = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
                "placeholder": "99",
                "step": "0.001",
            }
        ),
    )
    notes = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm bg-dark text-light border-secondary",
                "placeholder": "Flagged high",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        marker_name = (cleaned_data.get("marker_name") or "").strip()
        value = cleaned_data.get("value")
        unit = (cleaned_data.get("unit") or "").strip()
        reference_low = cleaned_data.get("reference_low")
        reference_high = cleaned_data.get("reference_high")
        notes = (cleaned_data.get("notes") or "").strip()

        has_any_value = any(
            [
                marker_name,
                value is not None,
                unit,
                reference_low is not None,
                reference_high is not None,
                notes,
            ]
        )

        if has_any_value and not marker_name:
            self.add_error("marker_name", "Enter a marker name.")
        if has_any_value and value is None:
            self.add_error("value", "Enter a result value.")
        if (
            reference_low is not None
            and reference_high is not None
            and reference_low > reference_high
        ):
            self.add_error(
                "reference_high",
                "Reference high must be greater than or equal to reference low.",
            )

        cleaned_data["marker_name"] = marker_name
        cleaned_data["unit"] = unit
        cleaned_data["notes"] = notes
        return cleaned_data


from django.forms import formset_factory

BloodworkMeasurementFormSet = formset_factory(
    BloodworkMeasurementForm,
    extra=1,
    max_num=None,
    validate_max=False,
)
