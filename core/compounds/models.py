from django.db import models
from django.utils.text import slugify
from django.conf import settings



class CompoundCategories(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Compound Category"
        verbose_name_plural = "Compound Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

class Target(models.Model):
    name = models.CharField(max_length=255, unique=True, help_text="Name of the target (e.g., GABA-A receptor, Dopamine transporter)")

    class Meta:
        verbose_name = "Target"
        verbose_name_plural = "Targets"
        ordering = ['name']

    def __str__(self):
        return self.name

class CompoundMechanismOfAction(models.Model):
    INTERACTION_TYPES = [
        ('agonist', 'Agonist'),
        ('antagonist', 'Antagonist'),
        ('partial_agonist', 'Partial Agonist'),
        ('inverse_agonist', 'Inverse Agonist'),
        ('pam', 'Positive Allosteric Modulator'),
        ('nam', 'Negative Allosteric Modulator'),
        ('binder', 'Binder'),
        ('inhibitor', 'Inhibitor'),
        ('activator', 'Activator'),
        ('upregulator', 'Upregulator'),
        ('downregulator', 'Downregulator'),
        ('unknown', 'Unknown'),
    ]
    
    TARGET_TYPES = [
        ('receptor', 'Receptor'),
        ('enzyme', 'Enzyme'),
        ('ion_channel', 'Ion Channel'),
        ('transporter', 'Transporter'),
        ('protein', 'Protein'),
        ('other', 'Other'),
    ]
    
    target_name = models.ForeignKey(
        Target,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mechanisms',
        help_text="Target this mechanism acts on"
    )
    target_type = models.CharField(
        max_length=100,
        choices=TARGET_TYPES,
        blank=True,
        help_text="Type of target (e.g., receptor, enzyme, ion channel, transporter)"
    )
    target_interaction = models.CharField(
        max_length=50,
        choices=INTERACTION_TYPES,
        blank=True,
        help_text="Type of interaction with the target (e.g., agonist, antagonist, etc.)"
    )
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Compound Mechanism of Action"
        verbose_name_plural = "Compound Mechanisms of Action"
        ordering = ['target_name']

    def __str__(self):
        return f"{self.target_name} - {self.target_interaction}" if self.target_name else "Mechanism"
    

class Compound(models.Model):
    name = models.CharField(max_length=500, unique=True)
    description = models.TextField(blank=True)
    slug = models.SlugField(unique=True, blank=True)
    aliases = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-saparated alternative names or acronyms."
    )
    smiles = models.CharField(
        max_length=1000,
        blank=True,
        help_text="SMILES notation for molecular structure"
    )
    categories = models.ManyToManyField(
        CompoundCategories,
        related_name='compounds',
        blank=True,
    )
    mechanism_of_action = models.ManyToManyField(
        CompoundMechanismOfAction,
        related_name='compounds',
        blank=True,
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CompoundRating(models.Model):
    compound = models.ForeignKey('Compound', on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        help_text="Rate compound based on likelihood of recommending. (1 to 5)",
    )
    comment = models.TextField(blank=True, help_text="Describe experience (optional)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('compound', 'user')

    def __str__(self):
        return f"{self.user} & {self.compound}: {self.score}"



class CompoundSafetyScreening(models.Model):
    compound    = models.OneToOneField('Compound', on_delete=models.CASCADE, related_name='safety_screening')

    liver_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        blank=True, null=True,
        help_text="1 = No toxicity observed; 5 = Lethal toxicity",
    )
    kidney_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        blank=True, null=True,
        help_text="1 = No toxicity observed; 5 = Lethal toxicity",
    )
    cardiovascular_risk = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        blank=True, null=True,
        help_text="1 = No risk observed; 5 = Lethal risk",
    )
    hpta_suppression = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1, 6)],
        blank=True, null=True,
        help_text="1 = No suppression observed; 5 = Full suppression",
    )
    neurotoxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1, 6)],
        blank=True, null=True,
        help_text="1 = No toxicity observed; 5 = Lethal toxicity",
    )
    lung_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        blank=True, null=True,
        help_text="1 = No toxicity observed; 5 = Lethal toxicity",
    )
    pancreas_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        blank=True, null=True,
        help_text="1 = No toxicity observed; 5 = Lethal toxicity",
    )
    bladder_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
        blank=True, null=True,
        help_text="1 = No toxicity observed; 5 = Lethal toxicity",
    )

    confidence_score = models.PositiveSmallIntegerField(
        choices=[(i, f"{i}/5") for i in range (1,6)],
        blank=True, null=True,
        help_text="How confident are you in the data provided?"
    )
    reference_link = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Compound Safety Screening"

    def __str__(self):
        return f"{self.compound.name} Safety Report by {self.created_by or 'Anonymous'}"


class EffectWindow(models.Model):
    """
    Model to define effect curves for compounds showing intensity over time.
    Used for visualizing pharmacokinetic profiles.
    """
    
    EFFECT_SHAPE_CHOICES = [
        ('bell', 'Bell Curve'),
        ('ramp', 'Ramp Up'),
        ('flat-top', 'Flat Top'),
        ('custom', 'Custom'),
    ]
    
    compound = models.ForeignKey(
        'Compound', 
        on_delete=models.CASCADE, 
        related_name='effect_windows',
        help_text="Compound this effect profile belongs to"
    )
    
    # Timing parameters (in minutes)
    onset_minutes = models.PositiveIntegerField(
        help_text="Smallest time after intake before effects begin (minutes)"
    )
    peak_min_minutes = models.PositiveIntegerField(
        help_text="Smallest time to peak effects (minutes)"
    )
    peak_max_minutes = models.PositiveIntegerField(
        help_text="Largest time to peak effects (minutes)"
    )
    duration_minutes = models.PositiveIntegerField(
        help_text="Total time of effects (minutes)"
    )
    half_life_minutes = models.PositiveIntegerField(
        blank=True, null=True,
        help_text="Optional half-life for decay visualization (minutes)"
    )
    
    # Effect profile
    effect_shape = models.CharField(
        max_length=20,
        choices=EFFECT_SHAPE_CHOICES,
        default='bell',
        help_text="Preset curve profile shape"
    )
    
    # Additional info
    notes = models.CharField(
        max_length=500,
        blank=True,
        help_text="Additional notes about this effect profile"
    )
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Effect Window"
        verbose_name_plural = "Effect Windows"
    
    def __str__(self):
        return f"{self.compound.name} - {self.get_effect_shape_display()}"
    
    def clean(self):
        """Validate timing constraints"""
        from django.core.exceptions import ValidationError
        
        if self.peak_min_minutes < self.onset_minutes:
            raise ValidationError("Peak minimum cannot be before onset")
        
        if self.peak_max_minutes < self.peak_min_minutes:
            raise ValidationError("Peak maximum cannot be before peak minimum")
        
        if self.duration_minutes < self.peak_max_minutes:
            raise ValidationError("Duration cannot be shorter than peak maximum")
    
    @property
    def peak_duration_minutes(self):
        """Calculate the duration of peak effects"""
        return self.peak_max_minutes - self.peak_min_minutes
    
    @property
    def comedown_minutes(self):
        """Calculate comedown duration"""
        return self.duration_minutes - self.peak_max_minutes
    
    def get_effect_curve_data(self, resolution_minutes=5):
        """
        Generate effect curve data points for visualization.
        Returns list of (time_minutes, intensity_percentage) tuples.
        """
        data_points = []
        time_range = range(0, self.duration_minutes + 1, resolution_minutes)
        
        for t in time_range:
            intensity = self._calculate_intensity_at_time(t)
            data_points.append((t, intensity))
        
        return data_points
    
    def _calculate_intensity_at_time(self, time_minutes):
        """Calculate effect intensity (0-100%) at given time"""
        if time_minutes < self.onset_minutes:
            return 0
        
        if time_minutes > self.duration_minutes:
            return 0
        
        if self.effect_shape == 'bell':
            return self._bell_curve_intensity(time_minutes)
        elif self.effect_shape == 'ramp':
            return self._ramp_intensity(time_minutes)
        elif self.effect_shape == 'flat-top':
            return self._flat_top_intensity(time_minutes)
        else:  # custom or fallback
            return self._bell_curve_intensity(time_minutes)
    
    def _bell_curve_intensity(self, time_minutes):
        """Bell curve intensity calculation"""
        if time_minutes <= self.onset_minutes:
            return 0
        elif time_minutes <= self.peak_min_minutes:
            # Rising phase
            progress = (time_minutes - self.onset_minutes) / (self.peak_min_minutes - self.onset_minutes)
            return min(100, progress * 100)
        elif time_minutes <= self.peak_max_minutes:
            # Peak phase
            return 100
        else:
            # Falling phase
            if self.half_life_minutes:
                # Exponential decay
                time_since_peak = time_minutes - self.peak_max_minutes
                decay_factor = 0.5 ** (time_since_peak / self.half_life_minutes)
                return max(0, 100 * decay_factor)
            else:
                # Linear decay
                falling_duration = self.duration_minutes - self.peak_max_minutes
                time_since_peak = time_minutes - self.peak_max_minutes
                progress = time_since_peak / falling_duration
                return max(0, 100 * (1 - progress))
    
    def _ramp_intensity(self, time_minutes):
        """Ramp up intensity calculation"""
        if time_minutes <= self.onset_minutes:
            return 0
        elif time_minutes <= self.peak_max_minutes:
            # Rising phase
            progress = (time_minutes - self.onset_minutes) / (self.peak_max_minutes - self.onset_minutes)
            return min(100, progress * 100)
        else:
            # Immediate fall
            falling_duration = self.duration_minutes - self.peak_max_minutes
            time_since_peak = time_minutes - self.peak_max_minutes
            progress = time_since_peak / falling_duration
            return max(0, 100 * (1 - progress))
    
    def _flat_top_intensity(self, time_minutes):
        """Flat top intensity calculation"""
        if time_minutes <= self.onset_minutes:
            return 0
        elif time_minutes <= self.peak_min_minutes:
            # Rising phase
            progress = (time_minutes - self.onset_minutes) / (self.peak_min_minutes - self.onset_minutes)
            return min(100, progress * 100)
        elif time_minutes <= self.peak_max_minutes:
            # Flat peak phase
            return 100
        else:
            # Falling phase
            falling_duration = self.duration_minutes - self.peak_max_minutes
            time_since_peak = time_minutes - self.peak_max_minutes
            progress = time_since_peak / falling_duration
            return max(0, 100 * (1 - progress))






