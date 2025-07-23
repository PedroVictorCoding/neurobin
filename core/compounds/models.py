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
        f"{self.compound.name} Safety Report by {self.created_by or 'Anonymous'}"






