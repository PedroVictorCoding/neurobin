from django import forms
from django.utils import timezone

from compounds.models import Compound

from .models import StackItem


class AddCompoundForm(forms.ModelForm):
    compound = forms.ModelChoiceField(
        queryset=Compound.objects.none(),
        widget=forms.Select(
            attrs={
                'class': 'form-select searchable w-100',
            }
        ),
    )
    intake_clock = forms.TimeField(
        required=False,
        widget=forms.TimeInput(
            attrs={
                'class': 'form-control w-100',
                'type': 'time',
            }
        ),
    )

    class Meta:
        model = StackItem
        fields = [
            'compound',
            'dosage_amount',
            'dosage_unit',
            'time_of_day',
            'recurrence_interval',
            'recurrence_unit',
            'doses_per_recurrence',
            'cycle_on_days',
            'cycle_off_days',
            'cycle_reference_date',
            'notes',
        ]
        widgets = {
            'dosage_amount': forms.NumberInput(
                attrs={
                    'class': 'form-control w-100',
                    'step': '0.01',
                    'placeholder': 'Dosage',
                }
            ),
            'dosage_unit': forms.Select(
                attrs={
                    'class': 'form-select w-100',
                }
            ),
            'recurrence_interval': forms.NumberInput(
                attrs={
                    'class': 'form-control w-100',
                    'min': '1',
                }
            ),
            'recurrence_unit': forms.Select(
                attrs={
                    'class': 'form-select w-100',
                }
            ),
            'time_of_day': forms.Select(
                attrs={
                    'class': 'form-select w-100',
                }
            ),
            'doses_per_recurrence': forms.NumberInput(
                attrs={
                    'class': 'form-control w-100',
                    'min': '1',
                    'max': '12',
                }
            ),
            'cycle_on_days': forms.NumberInput(
                attrs={
                    'class': 'form-control w-100',
                    'min': '1',
                    'placeholder': 'e.g. 5',
                }
            ),
            'cycle_off_days': forms.NumberInput(
                attrs={
                    'class': 'form-control w-100',
                    'min': '1',
                    'placeholder': 'e.g. 2',
                }
            ),
            'cycle_reference_date': forms.DateInput(
                attrs={
                    'class': 'form-control w-100',
                    'type': 'date',
                }
            ),
            'notes': forms.TextInput(
                attrs={
                    'class': 'form-control w-100',
                    'placeholder': 'Notes (optional)',
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['intake_clock'].label = 'Exact Intake Time'
        self.fields['intake_clock'].help_text = (
            'Hours only. The next upcoming date is inferred automatically.'
        )
        self.fields['recurrence_interval'].label = 'Frequency'
        self.fields['recurrence_interval'].help_text = (
            'Times per selected period (for example: 4 + Weekly = 4x/week).'
        )
        self.fields['recurrence_unit'].label = 'Period'
        self.fields['doses_per_recurrence'].label = 'Doses per Period'
        self.fields['doses_per_recurrence'].required = False
        self.fields['doses_per_recurrence'].help_text = (
            'Split each recurrence period into this many equally-spaced doses (e.g. 2 = morning + evening).'
        )
        self.fields['cycle_on_days'].label = 'Cycle On (days)'
        self.fields['cycle_on_days'].help_text = 'Active days per cycle. Leave blank to disable cycling.'
        self.fields['cycle_off_days'].label = 'Cycle Off (days)'
        self.fields['cycle_off_days'].help_text = 'Rest days per cycle (e.g. 5 on / 2 off).'
        self.fields['cycle_reference_date'].label = 'Cycle Start Date'
        self.fields['cycle_reference_date'].help_text = 'Day 1 of the first active cycle.'

        if not self.is_bound and getattr(self.instance, 'intake_time', None):
            intake_time = self.instance.intake_time
            if timezone.is_naive(intake_time):
                intake_time = timezone.make_aware(intake_time, timezone.get_current_timezone())
            self.initial['intake_clock'] = timezone.localtime(intake_time).time().replace(
                second=0,
                microsecond=0,
            )

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

    def clean(self):
        cleaned_data = super().clean()
        intake_clock = cleaned_data.get('intake_clock')
        if not intake_clock:
            cleaned_data['resolved_intake_time'] = None
            return cleaned_data

        from .services import add_recurrence

        local_now = timezone.localtime()
        scheduled_local = local_now.replace(
            hour=intake_clock.hour,
            minute=intake_clock.minute,
            second=0,
            microsecond=0,
        )
        recurrence_interval = cleaned_data.get('recurrence_interval') or 1
        recurrence_unit = cleaned_data.get('recurrence_unit') or 'daily'

        safety_counter = 0
        while scheduled_local <= local_now and safety_counter < 96:
            scheduled_local = add_recurrence(scheduled_local, recurrence_interval, recurrence_unit)
            safety_counter += 1

        cleaned_data['resolved_intake_time'] = scheduled_local
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.intake_time = self.cleaned_data.get('resolved_intake_time')
        # doses_per_recurrence is optional in the form; default to 1 if not supplied.
        if not instance.doses_per_recurrence:
            instance.doses_per_recurrence = 1
        if commit:
            instance.save()
            self.save_m2m()
        return instance
