import html
import re

from django.db import models
from django.utils.text import slugify
from django.conf import settings


class ActionType(models.Model):
    """Standardized action types for compound-target interactions"""
    name = models.CharField(max_length=100, unique=True, help_text="Action type (e.g., agonist, antagonist, inhibitor)")
    display_name = models.CharField(max_length=100, help_text="Human-readable display name")
    description = models.TextField(blank=True, help_text="Description of this action type")
    category = models.CharField(max_length=50, blank=True, help_text="Broad category (e.g., activation, inhibition, modulation)")
    
    class Meta:
        verbose_name = "Action Type"
        verbose_name_plural = "Action Types"
        ordering = ['name']
    
    def __str__(self):
        return self.display_name or self.name


class TargetType(models.Model):
    """Standardized target types for biological targets"""
    name = models.CharField(max_length=100, unique=True, help_text="Target type (e.g., receptor, enzyme, ion_channel)")
    display_name = models.CharField(max_length=100, help_text="Human-readable display name")
    description = models.TextField(blank=True, help_text="Description of this target type")
    category = models.CharField(max_length=50, blank=True, help_text="Broad category (e.g., membrane, intracellular, secreted)")
    
    class Meta:
        verbose_name = "Target Type"
        verbose_name_plural = "Target Types"
        ordering = ['name']
    
    def __str__(self):
        return self.display_name or self.name


def normalize_target_name(raw: str | None) -> str:
    """Normalize target names for consistent storage/display."""
    if raw is None:
        return ""

    text = html.unescape(str(raw)).strip()
    # Keep subscript content, drop the tag wrappers.
    text = re.sub(r"</?\s*sub\b[^>]*>", "", text, flags=re.IGNORECASE)
    # Drop any other HTML tags that might leak from external datasets.
    text = re.sub(r"<[^>]+>", "", text)
    text = " ".join(text.split())
    if not text:
        return ""

    # Normalize common serotonin receptor naming variants.
    text = re.sub(r"(?i)\b5-ht\b", "5-HT", text)
    text = re.sub(
        r"(?i)\b5-HT\s+(\d+[a-zA-Z]?)\b",
        lambda match: f"5-HT{match.group(1).upper()}",
        text,
    )
    text = re.sub(
        r"(?i)\b5-HT(\d+[a-zA-Z]?)\s+receptor\b",
        lambda match: f"5-HT{match.group(1).upper()} receptor",
        text,
    )
    return text


def normalize_compound_name(raw: str | None) -> str:
    """Normalize compound names for storage and matching."""
    if raw is None:
        return ""

    text = html.unescape(str(raw)).strip()
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("–", "-").replace("—", "-")
    text = " ".join(text.split())
    return text


def normalize_compound_lookup_key(raw: str | None) -> str:
    """Aggressive normalization key used for approximate matching."""
    text = normalize_compound_name(raw).lower()
    # Drop punctuation/spacing to match variants like 'N,N-DMT' vs 'N N DMT'.
    return re.sub(r"[^a-z0-9]+", "", text)


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
    TARGET_TYPES = [
        ('receptor', 'Receptor'),
        ('enzyme', 'Enzyme'),
        ('ion_channel', 'Ion Channel'),
        ('transporter', 'Transporter'),
        ('protein', 'Protein'),
        ('other', 'Other'),
        ('unknown', 'Unknown'),
    ]
    
    name = models.CharField(max_length=255, unique=True, help_text="Name of the target (e.g., GABA-A receptor, Dopamine transporter)")
    chembl_id = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        unique=True,
        help_text="ChEMBL target ID (e.g., CHEMBL2095189)"
    )
    target_type = models.CharField(
        max_length=100,
        choices=TARGET_TYPES,
        default='unknown',
        help_text="Type of target (e.g., receptor, enzyme, ion channel, transporter)"
    )
    # Keep the old 'type' field for backward compatibility
    type = models.CharField(
        max_length=100,
        choices=TARGET_TYPES,
        default='receptor',
        help_text="Type of target (deprecated, use target_type)"
    )
    # New structured target type reference
    structured_target_type = models.ForeignKey(
        TargetType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Structured target type reference"
    )
    description = models.TextField(blank=True, help_text="Detailed description of the target")
    organism = models.CharField(
        max_length=255, 
        blank=True, 
        help_text="Organism (e.g., Homo sapiens, Mus musculus)"
    )
    gene_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Gene name/symbol (e.g., HTR2A, DRD2)"
    )

    class Meta:
        verbose_name = "Target"
        verbose_name_plural = "Targets"
        ordering = ['name']

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_target_name(self.name)

        # Sync target_type with type field for backward compatibility
        if not self.target_type or self.target_type == 'unknown':
            self.target_type = self.type
        super().save(*args, **kwargs)

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
    chembl_id = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        unique=True,
        help_text="ChEMBL compound ID (e.g., CHEMBL25)"
    )
    bindingdb_id = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        unique=True,
        help_text="BindingDB monomer ID (e.g., 50058958)",
    )
    pubchem_cid = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        unique=True,
        help_text="PubChem Compound ID (CID)",
    )
    inchi = models.CharField(
        max_length=4000,
        blank=True,
        null=True,
        unique=True,
        help_text="IUPAC International Chemical Identifier (InChI)",
    )
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
    inchi_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Hashed InChIKey identifier",
    )
    iupac_name = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        help_text="IUPAC preferred compound name",
    )
    molecular_formula = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Molecular formula (for example C8H10N4O2)",
    )
    molecular_weight = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Molecular weight in g/mol",
    )
    mechanism_of_action_summary = models.TextField(
        blank=True,
        default="",
        help_text="Primary external mechanism summary from upstream sources",
    )
    pubmed_interactions = models.JSONField(
        default=list,
        blank=True,
        help_text="Cached PubMed interaction-focused references",
    )
    enriched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time external enrichment sources were checked",
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
    standard_dose = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Typical therapeutic or standard human dose (e.g. 5 for Donepezil 5mg)",
    )
    standard_dose_unit = models.CharField(
        max_length=16,
        blank=True,
        default='mg',
        help_text="Unit for standard_dose (mg, mcg, g, IU, etc.)",
    )
    views = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this compound page has been viewed"
    )

    def save(self, *args, **kwargs):
        if self.name:
            self.name = normalize_compound_name(self.name)
        if self.aliases:
            cleaned_aliases = [normalize_compound_name(part) for part in self.aliases.split(",")]
            cleaned_aliases = [part for part in cleaned_aliases if part]
            deduped = []
            seen = set()
            for alias in cleaned_aliases:
                key = alias.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(alias)
            self.aliases = ", ".join(deduped)
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
    def increment_views(self):
        """Safely increment view count using F() to avoid race conditions"""
        from django.db.models import F
        Compound.objects.filter(pk=self.pk).update(views=F('views') + 1)
        self.refresh_from_db(fields=['views'])
    
    def get_interactions(self):
        """Get all interactions involving this compound"""
        from django.db.models import Q
        return CompoundToCompoundTargetInteraction.objects.filter(
            Q(compound_a=self) | Q(compound_b=self)
        ).select_related('compound_a', 'compound_b', 'target', 'created_by')

    @property
    def missing_enrichment(self) -> bool:
        required_values = [
            self.smiles,
            self.pubchem_cid,
            self.inchi,
            self.inchi_key,
            self.iupac_name,
            self.molecular_formula,
            self.molecular_weight,
            self.mechanism_of_action_summary,
        ]
        if any(not (value or "").strip() for value in required_values):
            return True
        return not bool(self.pubmed_interactions)


class CompoundSteroidRating(models.Model):
    compound = models.OneToOneField(
        'Compound',
        on_delete=models.CASCADE,
        related_name='steroid_ratings',
    )
    anabolic_rating = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Relative anabolic rating (commonly testosterone=100 baseline).",
    )
    androgenic_rating = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Relative androgenic rating (commonly testosterone=100 baseline).",
    )
    ester_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=1.0,
        help_text=(
            "Fraction of active (ester-free) hormone per mg of compound. "
            "Computed as free_MW / compound_MW.  Oral / ester-free = 1.0."
        ),
    )

    def __str__(self):
        return f"{self.compound.name} steroid ratings"


class CompoundADMETPrediction(models.Model):
    compound = models.OneToOneField(
        'Compound',
        on_delete=models.CASCADE,
        related_name='admet_ai_prediction',
    )
    smiles = models.CharField(max_length=1000)
    smiles_sha256 = models.CharField(max_length=64)
    model_version = models.CharField(max_length=64, blank=True)
    predictions = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-computed_at']
        indexes = [
            models.Index(fields=['computed_at'], name='comp_admet_computed_at_idx'),
        ]

    def __str__(self):
        return f"ADMET-AI prediction for {self.compound.name}"


class CompoundMolPropPrediction(models.Model):
    compound = models.OneToOneField(
        'Compound',
        on_delete=models.CASCADE,
        related_name='molprop_prediction',
    )
    smiles = models.CharField(max_length=1000)
    smiles_sha256 = models.CharField(max_length=64)
    model_version = models.CharField(max_length=64, blank=True)
    predictions = models.JSONField(default=dict, blank=True)
    uncertainty = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-computed_at']
        indexes = [
            models.Index(fields=['computed_at'], name='comp_molprop_comp_at_idx'),
        ]

    def __str__(self):
        return f"MolProp prediction for {self.compound.name}"


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
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No toxicity observed; 5 = Lethal toxicity",
    )
    kidney_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No toxicity observed; 5 = Lethal toxicity",
    )
    cardiovascular_risk = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No risk observed; 5 = Lethal risk",
    )
    hpta_suppression = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No suppression observed; 5 = Full suppression",
    )
    neurotoxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No toxicity observed; 5 = Lethal toxicity",
    )
    lung_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No toxicity observed; 5 = Lethal toxicity",
    )
    pancreas_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No toxicity observed; 5 = Lethal toxicity",
    )
    bladder_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(0, 6)],
        blank=True, null=True,
        help_text="0 = Protective effect; 1 = No toxicity observed; 5 = Lethal toxicity",
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
        
        # Generate points from 0 to onset with 0% intensity
        for t in range(0, self.onset_minutes + 1, resolution_minutes):
            data_points.append((t, 0))
        
        # Ensure we have the exact onset point
        if data_points and data_points[-1][0] != self.onset_minutes:
            data_points.append((self.onset_minutes, 0))
        
        # Generate rising phase points (onset to peak_min)
        rising_duration = self.peak_min_minutes - self.onset_minutes
        if rising_duration > 0:
            num_rising_points = max(10, rising_duration // resolution_minutes)
            for i in range(1, num_rising_points + 1):
                time_point = self.onset_minutes + (i * rising_duration / num_rising_points)
                if time_point <= self.peak_min_minutes:
                    intensity = self._calculate_intensity_at_time(time_point)
                    data_points.append((time_point, intensity))
        
        # Add peak_min point (start of plateau)
        data_points.append((self.peak_min_minutes, 100))
        
        # Generate plateau phase points if there's a difference between peak_min and peak_max
        plateau_duration = self.peak_max_minutes - self.peak_min_minutes
        if plateau_duration > 0:
            num_plateau_points = max(5, plateau_duration // resolution_minutes)
            for i in range(1, num_plateau_points):
                time_point = self.peak_min_minutes + (i * plateau_duration / num_plateau_points)
                data_points.append((time_point, 100))
        
        # Add peak_max point (end of plateau, start of decline)
        data_points.append((self.peak_max_minutes, 100))
        
        # Generate falling phase points with linear decline
        falling_duration = self.duration_minutes - self.peak_max_minutes
        if falling_duration > 0:
            # Generate sufficient points for smooth linear decline
            num_falling_points = max(20, falling_duration // 2)
            
            for i in range(1, num_falling_points + 1):
                time_point = self.peak_max_minutes + (i * falling_duration / num_falling_points)
                if time_point < self.duration_minutes:
                    intensity = self._calculate_intensity_at_time(time_point)
                    data_points.append((time_point, intensity))
        
        # Always add the final point at duration_minutes with 0% intensity
        data_points.append((self.duration_minutes, 0))
        
        return data_points
    
    def _calculate_intensity_at_time(self, time_minutes):
        """Calculate effect intensity (0-100%) at given time"""
        if time_minutes < self.onset_minutes:
            return 0
        
        if time_minutes > self.duration_minutes:
            return 0
        
        # At exactly duration_minutes, intensity should be 0
        if time_minutes == self.duration_minutes:
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
        """Bell curve intensity calculation with linear decline"""
        if time_minutes <= self.onset_minutes:
            return 0
        elif time_minutes <= self.peak_min_minutes:
            # Rising phase - linear from 0% to 100%
            progress = (time_minutes - self.onset_minutes) / (self.peak_min_minutes - self.onset_minutes)
            return min(100, progress * 100)
        elif time_minutes <= self.peak_max_minutes:
            # Peak phase - constant 100%
            return 100
        else:
            # Falling phase - linear decline from 100% to 0%
            falling_duration = self.duration_minutes - self.peak_max_minutes
            if falling_duration <= 0:
                return 0
            
            if time_minutes >= self.duration_minutes:
                return 0
                
            time_since_peak = time_minutes - self.peak_max_minutes
            # Linear decline: starts at 100% and decreases linearly to 0%
            progress = time_since_peak / falling_duration
            intensity = 100 * (1 - progress)
            return max(0, intensity)
    
    def _ramp_intensity(self, time_minutes):
        """Ramp up intensity calculation with linear decline"""
        if time_minutes <= self.onset_minutes:
            return 0
        elif time_minutes <= self.peak_max_minutes:
            # Rising phase - linear from 0% to 100%
            progress = (time_minutes - self.onset_minutes) / (self.peak_max_minutes - self.onset_minutes)
            return min(100, progress * 100)
        else:
            # Falling phase - linear decline from 100% to 0%
            falling_duration = self.duration_minutes - self.peak_max_minutes
            if falling_duration <= 0:
                return 0
            
            if time_minutes >= self.duration_minutes:
                return 0
                
            time_since_peak = time_minutes - self.peak_max_minutes
            # Linear decline: starts at 100% and decreases linearly to 0%
            progress = time_since_peak / falling_duration
            intensity = 100 * (1 - progress)
            return max(0, intensity)
    
    def _flat_top_intensity(self, time_minutes):
        """Flat top intensity calculation with linear decline"""
        if time_minutes <= self.onset_minutes:
            return 0
        elif time_minutes <= self.peak_min_minutes:
            # Rising phase - linear from 0% to 100%
            progress = (time_minutes - self.onset_minutes) / (self.peak_min_minutes - self.onset_minutes)
            return min(100, progress * 100)
        elif time_minutes <= self.peak_max_minutes:
            # Flat peak phase - constant 100%
            return 100
        else:
            # Falling phase - linear decline from 100% to 0%
            falling_duration = self.duration_minutes - self.peak_max_minutes
            if falling_duration <= 0:
                return 0
                
            if time_minutes >= self.duration_minutes:
                return 0
                
            time_since_peak = time_minutes - self.peak_max_minutes
            # Linear decline: starts at 100% and decreases linearly to 0%
            progress = time_since_peak / falling_duration
            intensity = 100 * (1 - progress)
            return max(0, intensity)


class CompoundTargetInteraction(models.Model):
    """Defines how one compound acts on a single target"""
    MECHANISM_CHOICES = [
        ('agonist', 'Agonist'),
        ('antagonist', 'Antagonist'),
        ('partial_agonist', 'Partial Agonist'),
        ('inverse_agonist', 'Inverse Agonist'),
        ('pam', 'Positive Allosteric Modulator'),
        ('nam', 'Negative Allosteric Modulator'),
        ('inhibitor', 'Inhibitor'),
        ('inducer', 'Inducer'),
        ('activator', 'Activator'),
        ('binder', 'Binder'),
        ('substrate', 'Substrate'),
        ('modulator', 'Modulator'),
        ('blocker', 'Blocker'),
        ('opener', 'Opener'),
        ('unknown', 'Unknown'),
    ]
    
    AFFINITY_CHOICES = [
        ('high', 'High (< 100 nM)'),
        ('medium', 'Medium (100-1000 nM)'),
        ('low', 'Low (> 1000 nM)'),
        ('very_high', 'Very High (< 10 nM)'),
        ('very_low', 'Very Low (> 10 μM)'),
        ('unknown', 'Unknown'),
    ]
    
    compound = models.ForeignKey('Compound', on_delete=models.CASCADE, related_name='target_interactions')
    target = models.ForeignKey('Target', on_delete=models.CASCADE, related_name='compound_interactions')
    mechanism = models.CharField(
        max_length=50,
        choices=MECHANISM_CHOICES,
        help_text="How the compound interacts with this target"
    )
    # New structured action type reference
    structured_action_type = models.ForeignKey(
        ActionType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Structured action type reference"
    )
    affinity_level = models.CharField(
        max_length=20,
        choices=AFFINITY_CHOICES,
        default='unknown',
        help_text="Binding affinity level"
    )
    notes = models.TextField(blank=True, help_text="Additional notes about this interaction")
    source = models.CharField(
        max_length=100,
        blank=True,
        help_text="Data source (e.g., ChEMBL, PubMed, manual)"
    )
    
    class Meta:
        unique_together = ('compound', 'target', 'mechanism')
        verbose_name = "Compound-Target Interaction"
        verbose_name_plural = "Compound-Target Interactions"
        ordering = ['compound', 'target']
    
    def __str__(self):
        return f"{self.compound.name} → {self.target.name} ({self.mechanism})"


class CompoundTargetInteractionEvidence(models.Model):
    """Atomic source evidence rows for a compound-target mechanism with context."""
    EVIDENCE_LEVEL_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('unknown', 'Unknown'),
    ]

    compound = models.ForeignKey(
        'Compound',
        on_delete=models.CASCADE,
        related_name='target_interaction_evidence',
    )
    target = models.ForeignKey(
        'Target',
        on_delete=models.CASCADE,
        related_name='compound_interaction_evidence',
    )
    source = models.CharField(
        max_length=50,
        help_text="Evidence source (e.g., IUPHAR, BindingDB, DrugBank, DGIdb, PharmGKB)",
    )
    source_record_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Source-native interaction identifier",
    )
    source_url = models.URLField(blank=True)
    source_row_uid = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        help_text="Stable row fingerprint for fast resume/skip across reruns",
    )
    evidence_uid = models.CharField(
        max_length=64,
        unique=True,
        help_text="Deterministic hash used to deduplicate imported evidence rows",
    )

    raw_action_type = models.CharField(max_length=255, blank=True)
    raw_mechanism = models.CharField(max_length=500, blank=True)
    canonical_mechanism = models.CharField(
        max_length=50,
        choices=CompoundTargetInteraction.MECHANISM_CHOICES,
        default='unknown',
    )

    species = models.CharField(max_length=255, blank=True)
    tissue_or_cell_line = models.CharField(max_length=255, blank=True)
    assay_type = models.CharField(max_length=255, blank=True)
    dose_concentration = models.CharField(max_length=255, blank=True)
    exposure_time = models.CharField(max_length=255, blank=True)
    route = models.CharField(max_length=100, blank=True)
    evidence_level = models.CharField(
        max_length=20,
        choices=EVIDENCE_LEVEL_CHOICES,
        default='unknown',
    )
    evidence_weight = models.FloatField(default=0.5)
    affinity_type = models.CharField(
        max_length=20,
        blank=True,
        help_text="Reported affinity metric (e.g., Ki, Kd, IC50, EC50)",
    )
    affinity_relation = models.CharField(
        max_length=10,
        blank=True,
        help_text="Reported relation/operator (e.g., =, <, >, ~)",
    )
    affinity_raw_value = models.CharField(
        max_length=64,
        blank=True,
        help_text="Original raw affinity value from source record",
    )
    affinity_units = models.CharField(
        max_length=32,
        blank=True,
        help_text="Original affinity units from source record",
    )
    affinity_value_nm = models.FloatField(
        null=True,
        blank=True,
        help_text="Normalized affinity value in nM for cross-source comparisons",
    )

    notes = models.TextField(blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    context_key = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Deterministic context key: species+tissue+assay+dose+time+route",
    )

    class Meta:
        verbose_name = "Compound-Target Interaction Evidence"
        verbose_name_plural = "Compound-Target Interaction Evidence"
        ordering = ['-imported_at']
        indexes = [
            models.Index(fields=['compound', 'target'], name='cti_ev_compound_target_idx'),
            models.Index(fields=['source'], name='cti_ev_source_idx'),
            models.Index(fields=['source_row_uid'], name='cti_ev_row_uid_idx'),
            models.Index(fields=['canonical_mechanism'], name='cti_ev_mechanism_idx'),
            models.Index(fields=['evidence_level'], name='cti_ev_level_idx'),
            models.Index(fields=['affinity_value_nm'], name='cti_ev_affinity_nm_idx'),
        ]

    def __str__(self):
        return (
            f"{self.compound.name} → {self.target.name} [{self.source}] "
            f"({self.canonical_mechanism}, {self.evidence_level})"
        )


class CompoundTargetContextConsensus(models.Model):
    """Consensus mechanism per compound-target-context computed from evidence rows."""
    CONFIDENCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    compound = models.ForeignKey(
        'Compound',
        on_delete=models.CASCADE,
        related_name='target_context_consensus',
    )
    target = models.ForeignKey(
        'Target',
        on_delete=models.CASCADE,
        related_name='compound_context_consensus',
    )
    context_key = models.CharField(max_length=255, db_index=True)

    species = models.CharField(max_length=255, blank=True)
    tissue_or_cell_line = models.CharField(max_length=255, blank=True)
    assay_type = models.CharField(max_length=255, blank=True)
    dose_concentration = models.CharField(max_length=255, blank=True)
    exposure_time = models.CharField(max_length=255, blank=True)
    route = models.CharField(max_length=100, blank=True)

    consensus_mechanism = models.CharField(
        max_length=50,
        choices=CompoundTargetInteraction.MECHANISM_CHOICES,
        default='unknown',
    )
    consensus_confidence = models.CharField(
        max_length=10,
        choices=CONFIDENCE_CHOICES,
        default='low',
    )
    has_conflict = models.BooleanField(default=False)
    unresolved_reason = models.CharField(max_length=255, blank=True)

    evidence_count = models.PositiveIntegerField(default=0)
    total_weight = models.FloatField(default=0.0)
    mechanism_weights = models.JSONField(default=dict, blank=True)
    source_breakdown = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compound-Target Context Consensus"
        verbose_name_plural = "Compound-Target Context Consensus"
        unique_together = ('compound', 'target', 'context_key')
        indexes = [
            models.Index(fields=['compound', 'target'], name='cti_ctx_compound_target_idx'),
            models.Index(fields=['consensus_mechanism'], name='cti_ctx_mechanism_idx'),
            models.Index(fields=['consensus_confidence'], name='cti_ctx_conf_idx'),
            models.Index(fields=['has_conflict'], name='cti_ctx_conflict_idx'),
        ]

    def __str__(self):
        return (
            f"{self.compound.name} → {self.target.name} [{self.context_key}] "
            f"{self.consensus_mechanism} ({self.consensus_confidence})"
        )


class CompoundToCompoundTargetInteraction(models.Model):
    """Represents an interaction between two compounds through a shared target"""
    INTERACTION_TYPE_CHOICES = [
        ('synergistic', 'Synergistic'),
        ('antagonistic', 'Antagonistic'),
        ('competitive', 'Competitive'),
        ('competitive_metabolism', 'Competitive Metabolism'),
        ('enzyme_inhibition', 'Enzyme Inhibition'),
        ('enzyme_induction', 'Enzyme Induction'),
        ('receptor_competition', 'Receptor Competition'),
        ('additive', 'Additive'),
        ('unknown', 'Unknown'),
    ]
    
    CONFIDENCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    
    compound_a = models.ForeignKey(
        'Compound', 
        on_delete=models.CASCADE, 
        related_name='interactions_as_compound_a',
        help_text="First compound in the interaction"
    )
    compound_b = models.ForeignKey(
        'Compound', 
        on_delete=models.CASCADE, 
        related_name='interactions_as_compound_b',
        help_text="Second compound in the interaction"
    )
    target = models.ForeignKey(
        'Target', 
        on_delete=models.CASCADE, 
        related_name='compound_compound_interactions',
        help_text="Shared target through which the interaction occurs"
    )
    interaction_type = models.CharField(
        max_length=50,
        choices=INTERACTION_TYPE_CHOICES,
        help_text="Type of interaction between the compounds"
    )
    description = models.TextField(
        help_text="Detailed description of the interaction (e.g., 'Compound A inhibits CYP2D6, delaying metabolism of Compound B')"
    )
    confidence = models.CharField(
        max_length=10,
        choices=CONFIDENCE_CHOICES,
        default='medium',
        help_text="Confidence level of this interaction data"
    )
    source = models.CharField(
        max_length=500,
        blank=True,
        help_text="Source reference (PubMed ID, DOI, or URL)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    
    class Meta:
        unique_together = ('compound_a', 'compound_b', 'target')
        verbose_name = "Compound-to-Compound Interaction"
        verbose_name_plural = "Compound-to-Compound Interactions"
        ordering = ['compound_a', 'compound_b', 'target']
    
    def __str__(self):
        return f"{self.compound_a.name} ↔ {self.compound_b.name} via {self.target.name}"
    
    def save(self, *args, **kwargs):
        # Ensure compound_a and compound_b are different
        if self.compound_a == self.compound_b:
            raise ValueError("A compound cannot interact with itself")
        
        # Ensure consistent ordering (compound_a.id < compound_b.id) to prevent duplicates
        if self.compound_a.id > self.compound_b.id:
            self.compound_a, self.compound_b = self.compound_b, self.compound_a
        
        super().save(*args, **kwargs)
    
    def get_compound_a_mechanism(self):
        """Get the mechanism of action for compound A on the shared target"""
        mechanisms = list(
            CompoundTargetInteraction.objects.filter(
                compound=self.compound_a,
                target=self.target
            ).order_by('mechanism').values_list('mechanism', flat=True).distinct()
        )
        if not mechanisms:
            return 'unknown'
        return ', '.join(mechanisms)
    
    def get_compound_b_mechanism(self):
        """Get the mechanism of action for compound B on the shared target"""
        mechanisms = list(
            CompoundTargetInteraction.objects.filter(
                compound=self.compound_b,
                target=self.target
            ).order_by('mechanism').values_list('mechanism', flat=True).distinct()
        )
        if not mechanisms:
            return 'unknown'
        return ', '.join(mechanisms)


class CompoundKnowledgeGraphRun(models.Model):
    """Execution record for Gemini-backed compound graph enrichment."""

    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
        ('blocked', 'Blocked'),
    ]

    compound = models.ForeignKey(
        'Compound',
        on_delete=models.CASCADE,
        related_name='knowledge_graph_runs',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_knowledge_graph_runs',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    model_name = models.CharField(max_length=100, blank=True)
    request_hash = models.CharField(max_length=64, db_index=True)
    include_internet = models.BooleanField(default=True)
    max_edges = models.PositiveIntegerField(default=25)
    edges_created = models.PositiveIntegerField(default=0)
    edges_rejected = models.PositiveIntegerField(default=0)
    edges_validated = models.PositiveIntegerField(default=0)
    cached_response_used = models.BooleanField(default=False)
    raw_response = models.JSONField(default=dict, blank=True)
    parsed_output = models.JSONField(
        default=dict,
        blank=True,
        help_text="Normalized Gemini JSON payload captured before moderation filtering",
    )
    moderation_notes = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['compound', 'created_at'], name='ckgr_comp_created_idx'),
            models.Index(fields=['compound', 'status'], name='ckgr_comp_status_idx'),
            models.Index(fields=['request_hash'], name='ckgr_req_hash_idx'),
        ]

    def __str__(self):
        return f"Graph run for {self.compound.name} ({self.status})"


class CompoundKnowledgeGraphEdge(models.Model):
    """Moderated graph edge generated from DB context + internet evidence."""

    NODE_KIND_CHOICES = [
        ('compound', 'Compound'),
        ('target', 'Target'),
        ('mechanism', 'Mechanism'),
        ('pathway', 'Pathway'),
        ('gene', 'Gene'),
        ('effect', 'Effect'),
        ('unknown', 'Unknown'),
    ]

    EVIDENCE_LEVEL_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('unknown', 'Unknown'),
    ]

    DB_VALIDATION_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('conflicting', 'Conflicting'),
        ('novel', 'Novel'),
        ('unresolved', 'Unresolved'),
        ('rejected', 'Rejected'),
    ]

    MODERATION_CHOICES = [
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    run = models.ForeignKey(
        CompoundKnowledgeGraphRun,
        on_delete=models.CASCADE,
        related_name='edges',
    )
    compound = models.ForeignKey(
        'Compound',
        on_delete=models.CASCADE,
        related_name='knowledge_graph_edges',
        help_text='Anchor compound for this graph edge',
    )
    subject_kind = models.CharField(max_length=20, choices=NODE_KIND_CHOICES, default='unknown')
    subject_label = models.CharField(max_length=255)
    predicate = models.CharField(max_length=100)
    object_kind = models.CharField(max_length=20, choices=NODE_KIND_CHOICES, default='unknown')
    object_label = models.CharField(max_length=255)
    related_compound = models.ForeignKey(
        'Compound',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='related_knowledge_graph_edges',
    )
    related_target = models.ForeignKey(
        'Target',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='knowledge_graph_edges',
    )
    canonical_mechanism = models.CharField(
        max_length=50,
        choices=CompoundTargetInteraction.MECHANISM_CHOICES,
        default='unknown',
    )
    confidence_score = models.FloatField(default=0.0)
    evidence_level = models.CharField(
        max_length=20,
        choices=EVIDENCE_LEVEL_CHOICES,
        default='unknown',
    )
    source_title = models.CharField(max_length=500, blank=True)
    source_url = models.URLField(blank=True)
    evidence_snippet = models.TextField(blank=True)
    db_validation_status = models.CharField(
        max_length=20,
        choices=DB_VALIDATION_CHOICES,
        default='unresolved',
    )
    moderation_status = models.CharField(
        max_length=20,
        choices=MODERATION_CHOICES,
        default='approved',
    )
    moderation_reason = models.CharField(max_length=255, blank=True)
    edge_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-confidence_score', '-created_at']
        indexes = [
            models.Index(fields=['compound', 'created_at'], name='ckge_comp_created_idx'),
            models.Index(fields=['db_validation_status'], name='ckge_validation_idx'),
            models.Index(fields=['canonical_mechanism'], name='ckge_mechanism_idx'),
            models.Index(fields=['predicate'], name='ckge_predicate_idx'),
        ]
        unique_together = ('run', 'edge_hash')

    def __str__(self):
        return f"{self.subject_label} -[{self.predicate}]-> {self.object_label}"
