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

class CompoundMechanismOfAction(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Compound Mechanism of Action"
        verbose_name_plural = "Compound Mechanisms of Action"
        ordering = ['name']

    def __str__(self):
        return self.name
    
class CompoundReceptorTargets(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Compound Receptor Target"
        verbose_name_plural = "Compound Receptor Targets"
        ordering = ['name']

    def __str__(self):
        return self.name


class Compound(models.Model):
    name = models.CharField(max_length=500, unique=True)
    description = models.TextField(blank=True)
    slug = models.SlugField(unique=True, blank=True)
    aliases = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-saparated alternative names or acronyms."
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
    receptor_targets = models.ManyToManyField(
        CompoundReceptorTargets,
        related_name='compounds',
        blank=True,
    )


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
    compound    = models.ForeignKey('Compound', unique=True, on_delete=models.CASCADE, related_name='safety_screening')

    liver_toxicity = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1,6)],
    )




