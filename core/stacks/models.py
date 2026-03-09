from django.conf import settings
from django.db import models

from compounds.models import Compound, CompoundTargetInteraction

class Stack(models.Model):
    VISIBILITY_CHOICES = [
        ('private', 'Private'),
        ('public', 'Public'),
        ('unlisted', 'Unlisted'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stacks')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    is_active = models.BooleanField(default=False)
    copied_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copies')
    copied_at = models.DateTimeField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class StackRiskAssessment(models.Model):
    RISK_LEVEL_CHOICES = [
        ('unknown', 'Unknown'),
        ('low', 'Low'),
        ('moderate', 'Moderate'),
        ('high', 'High'),
    ]

    stack = models.OneToOneField(
        Stack,
        on_delete=models.CASCADE,
        related_name='risk_assessment',
    )
    input_hash = models.CharField(max_length=64, db_index=True)
    compound_count = models.PositiveIntegerField(default=0)
    predicted_count = models.PositiveIntegerField(default=0)
    risk_score = models.FloatField(null=True, blank=True)
    risk_level = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='unknown')
    details = models.JSONField(default=dict, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-computed_at']

    def __str__(self):
        return f"Risk for {self.stack.name}: {self.risk_level}"


class StackItem(models.Model):
    DOSAGE_UNIT_CHOICES = [
        ('mg', 'mg'),
        ('g', 'g'),
        ('mcg', 'mcg'),
        ('ml', 'ml'),
        ('drops', 'drops'),
        ('units', 'units'),
        ('other', 'Other'),
    ]

    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name='items')
    compound = models.ForeignKey(Compound, on_delete=models.CASCADE)
    dosage_amount = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dosage_unit = models.CharField(max_length=16, choices=DOSAGE_UNIT_CHOICES, default='mg')
    TIME_OF_DAY_CHOICES = [
        ('morning', 'Morning'),
        ('afternoon', 'Afternoon'),
        ('night', 'Night'),
        ('pre-event', 'Pre-event'),
    ]
    time_of_day = models.CharField(max_length=10, choices=TIME_OF_DAY_CHOICES, default=None, blank=True, null=True)
    intake_time = models.DateTimeField(null=True, blank=True)
    # Recurrence settings
    RECURRENCE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    recurrence_interval = models.PositiveIntegerField(default=1)
    recurrence_unit = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, default='daily')
    order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    added = models.DateTimeField(auto_now_add=True)

    # Multi-dose: emit this many equally-spaced doses per recurrence period.
    doses_per_recurrence = models.PositiveIntegerField(
        default=1,
        help_text="Number of equally-spaced doses per recurrence period (e.g. 2 = morning + evening).",
    )

    # Drug holiday / cycling support.
    cycle_on_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Active days per cycle (e.g. 5 for 5-on/2-off). Leave blank to disable cycling.",
    )
    cycle_off_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Rest days per cycle (e.g. 2 for 5-on/2-off).",
    )
    cycle_reference_date = models.DateField(
        null=True, blank=True,
        help_text="Day 1 of the first cycle. Defaults to item creation date if cycling is enabled.",
    )

    class Meta:
        ordering = ['order', 'added']

    def __str__(self):
        return f"{self.compound.name} in {self.stack.name}"

    @property
    def recurrence_rate_label(self) -> str:
        """Display recurrence as a frequency (e.g. 1x/day, 4x/week)."""
        unit_map = {
            'daily': 'day',
            'weekly': 'week',
            'monthly': 'month',
        }
        unit_label = unit_map.get(self.recurrence_unit, self.recurrence_unit or 'unit')
        interval = self.recurrence_interval if self.recurrence_interval and self.recurrence_interval > 0 else 1
        return f"{interval}x/{unit_label}"


class StackTrait(models.Model):
    TRAIT_TYPE_CHOICES = [
        ('benefit', 'Benefit'),
        ('risk', 'Risk'),
    ]

    slug = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    trait_type = models.CharField(max_length=16, choices=TRAIT_TYPE_CHOICES, default='benefit')
    description = models.TextField(blank=True)
    is_hypothesis = models.BooleanField(
        default=False,
        help_text="Marks hypothesis-only traits (for example oncoprotection hypotheses).",
    )
    min_score = models.FloatField(default=-5.0)
    max_score = models.FloatField(default=5.0)
    default_weight = models.FloatField(default=1.0)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'label']

    def __str__(self):
        return self.label


class MechanismTraitRule(models.Model):
    mechanism = models.CharField(
        max_length=50,
        choices=CompoundTargetInteraction.MECHANISM_CHOICES,
        db_index=True,
    )
    trait = models.ForeignKey(
        StackTrait,
        on_delete=models.CASCADE,
        related_name='mechanism_rules',
    )
    delta = models.FloatField(
        help_text="Directional trait delta for this mechanism/rule. Typical range: -5..+5",
    )
    base_confidence = models.FloatField(
        default=0.7,
        help_text="Rule confidence multiplier in range 0..1.",
    )
    target_name_contains = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional substring filter to scope this rule to specific target families.",
    )
    species = models.CharField(max_length=255, blank=True)
    assay_type = models.CharField(max_length=255, blank=True)
    route = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    priority = models.IntegerField(
        default=100,
        help_text="Lower numbers are evaluated first and treated as more specific rules.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['priority', 'id']
        indexes = [
            models.Index(fields=['mechanism', 'is_active'], name='st_rule_mech_active_idx'),
            models.Index(fields=['trait', 'is_active'], name='st_rule_trait_active_idx'),
        ]

    def __str__(self):
        return f"{self.mechanism} -> {self.trait.slug} ({self.delta:+.2f})"


class StackDangerousPairRule(models.Model):
    SEVERITY_CHOICES = [
        ('moderate', 'Moderate'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    compound_a = models.ForeignKey(
        Compound,
        on_delete=models.CASCADE,
        related_name='dangerous_pairs_as_a',
    )
    compound_b = models.ForeignKey(
        Compound,
        on_delete=models.CASCADE,
        related_name='dangerous_pairs_as_b',
    )
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default='high')
    reason = models.CharField(max_length=255)
    source = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('compound_a', 'compound_b')
        indexes = [
            models.Index(fields=['compound_a', 'compound_b'], name='st_danger_pair_idx'),
            models.Index(fields=['is_active'], name='st_danger_active_idx'),
        ]

    def save(self, *args, **kwargs):
        if self.compound_a_id and self.compound_b_id and self.compound_a_id > self.compound_b_id:
            self.compound_a_id, self.compound_b_id = self.compound_b_id, self.compound_a_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.compound_a.name} + {self.compound_b.name} ({self.severity})"


class CompoundTaxonomyTag(models.Model):
    """
    Stores which stack-builder taxonomy subcategory a compound belongs to.
    Populated by: python manage.py populate_builder_tags
    """
    compound    = models.ForeignKey(Compound, on_delete=models.CASCADE, related_name='taxonomy_tags')
    group_id    = models.CharField(max_length=60, db_index=True)
    sub_id      = models.CharField(max_length=60, db_index=True)
    group_label = models.CharField(max_length=120, blank=True)
    sub_label   = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = ('compound', 'sub_id')
        indexes = [
            models.Index(fields=['sub_id'],   name='ctt_sub_idx'),
            models.Index(fields=['group_id'], name='ctt_grp_idx'),
        ]

    def __str__(self):
        return f"{self.compound.name} → {self.group_id}/{self.sub_id}"
