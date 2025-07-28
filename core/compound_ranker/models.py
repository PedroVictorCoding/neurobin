from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import User


class ScoringCategory(models.Model):
    """Categories for compound scoring and ranking"""
    name = models.CharField(max_length=64, unique=True, help_text="Category name (e.g., Longevity-enhancing)")
    description = models.TextField(help_text="Description of this scoring category")
    slug = models.SlugField(unique=True, help_text="URL-safe slug for this category")
    icon = models.CharField(max_length=128, blank=True, help_text="Icon class or emoji for display")
    is_active = models.BooleanField(default=True, help_text="Whether this category is actively scored")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Scoring Category"
        verbose_name_plural = "Scoring Categories"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_top_compounds(self, limit=10):
        """Get top N compounds for this category"""
        return self.compoundscore_set.select_related('compound').order_by('-score')[:limit]

    def get_compound_count(self):
        """Get total number of scored compounds for this category"""
        return self.compoundscore_set.count()


class CompoundScore(models.Model):
    """Stores ML-generated scores for compounds across different categories"""
    compound = models.ForeignKey('compounds.Compound', on_delete=models.CASCADE, related_name='ml_scores')
    category = models.ForeignKey(ScoringCategory, on_delete=models.CASCADE)
    score = models.FloatField(help_text="Predicted score (0-1 range)")
    confidence = models.FloatField(help_text="Model confidence in prediction (0-1 range)")
    model_version = models.CharField(max_length=64, blank=True, help_text="Version of ML model used")
    features_used = models.JSONField(default=dict, help_text="Features used for this prediction")
    timestamp = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compound Score"
        verbose_name_plural = "Compound Scores"
        ordering = ['-score', '-timestamp']
        unique_together = ['compound', 'category']  # One score per compound per category
        indexes = [
            models.Index(fields=['category', '-score']),
            models.Index(fields=['compound', 'category']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.compound.name} - {self.category.name}: {self.score:.3f}"

    @property
    def rank_in_category(self):
        """Get rank of this compound in its category"""
        return CompoundScore.objects.filter(
            category=self.category,
            score__gt=self.score
        ).count() + 1

    @property
    def score_percentage(self):
        """Get score as percentage for display"""
        return round(self.score * 100, 1)

    @property
    def confidence_percentage(self):
        """Get confidence as percentage for display"""
        return round(self.confidence * 100, 1)


class ModelTrainingLog(models.Model):
    """Logs for ML model training sessions"""
    category = models.ForeignKey(ScoringCategory, on_delete=models.CASCADE, null=True, blank=True)
    model_version = models.CharField(max_length=64)
    training_started = models.DateTimeField()
    training_completed = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('running', 'Training Running'),
        ('completed', 'Training Completed'),
        ('failed', 'Training Failed'),
    ], default='running')
    training_samples = models.IntegerField(default=0)
    validation_accuracy = models.FloatField(null=True, blank=True)
    validation_loss = models.FloatField(null=True, blank=True)
    hyperparameters = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    trained_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Model Training Log"
        verbose_name_plural = "Model Training Logs"
        ordering = ['-training_started']

    def __str__(self):
        category_name = self.category.name if self.category else "All Categories"
        return f"{category_name} - {self.model_version} ({self.status})"


class UserCompoundAnnotation(models.Model):
    """User-provided annotations for improving ML models"""
    compound = models.ForeignKey('compounds.Compound', on_delete=models.CASCADE)
    category = models.ForeignKey(ScoringCategory, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    user_score = models.FloatField(help_text="User-provided score (0-1 range)")
    notes = models.TextField(blank=True, help_text="User notes about this scoring")
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False, help_text="Whether this annotation has been verified")

    class Meta:
        verbose_name = "User Compound Annotation"
        verbose_name_plural = "User Compound Annotations"
        unique_together = ['compound', 'category', 'user']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.compound.name} - {self.category.name}: {self.user_score}"
