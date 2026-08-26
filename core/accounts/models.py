from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
import os
import uuid

def user_profile_image_path(instance, filename):
    """Generate file path for user profile images"""
    # Get file extension
    ext = filename.split('.')[-1]
    # Create new filename
    filename = f'profile_{instance.user.id}.{ext}'
    return os.path.join('profile_images', filename)

GOAL_SKIN_CHOICES = [
    ('general',     'General'),
    ('anabolic',    'Anabolic'),
    ('longevity',   'Longevity'),
    ('cognition',   'Cognition'),
    ('performance', 'Performance'),
    ('recovery',    'Recovery'),
    ('sleep',       'Sleep'),
    ('fat-loss',    'Fat Loss'),
]


class UserProfile(models.Model):
    """
    Extended user profile with additional fields including profile image.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    profile_image = models.ImageField(
        upload_to=user_profile_image_path,
        blank=True,
        null=True,
        help_text="Upload a profile picture"
    )
    bio = models.TextField(
        max_length=500,
        blank=True,
        help_text="Tell us about yourself"
    )
    location = models.CharField(
        max_length=100,
        blank=True,
        help_text="Your location"
    )
    website = models.URLField(
        blank=True,
        help_text="Your personal website or social media"
    )
    goal_skin = models.CharField(
        max_length=20,
        choices=GOAL_SKIN_CHOICES,
        default='general',
        help_text="Your primary goal defines the app color theme"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
    
    def __str__(self):
        return f"{self.user.username}'s Profile"
    
    @property
    def profile_image_url(self):
        """Return profile image URL or default placeholder"""
        if self.profile_image and hasattr(self.profile_image, 'url'):
            return self.profile_image.url
        return None


class ClinicalProfile(models.Model):
    """Restricted, user-owned research context; never exposed through public profiles."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='clinical_profile')
    consent_version = models.CharField(max_length=32)
    consented_at = models.DateTimeField()
    date_of_birth = models.DateField(null=True, blank=True)
    sex_at_birth = models.CharField(max_length=16, blank=True)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    pregnancy_status = models.CharField(max_length=24, blank=True)
    smoking_status = models.CharField(max_length=24, blank=True)
    egfr = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    egfr_measured_at = models.DateField(null=True, blank=True)
    child_pugh_class = models.CharField(max_length=1, blank=True)
    child_pugh_assessed_at = models.DateField(null=True, blank=True)
    diagnoses = models.JSONField(default=list, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PharmacogenomicResult(models.Model):
    profile = models.ForeignKey(ClinicalProfile, on_delete=models.CASCADE, related_name='pharmacogenomic_results')
    gene = models.CharField(max_length=32)
    diplotype = models.CharField(max_length=64, blank=True)
    phenotype = models.CharField(max_length=64, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['profile', 'gene'], name='unique_profile_pgx_gene')]


def clinical_document_path(instance, filename):
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    return f'private_clinical/{instance.user_id}/{uuid.uuid4().hex}.{extension}'


class ClinicalDocument(models.Model):
    STATUS_CHOICES = [('uploaded', 'Uploaded'), ('review', 'Needs review'), ('confirmed', 'Confirmed'), ('failed', 'Failed')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='clinical_documents')
    file = models.FileField(upload_to=clinical_document_path)
    sha256 = models.CharField(max_length=64, db_index=True)
    content_type = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='uploaded')
    extracted_text = models.TextField(blank=True)
    extraction_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ClinicalProfileDraftValue(models.Model):
    document = models.ForeignKey(ClinicalDocument, on_delete=models.CASCADE, related_name='draft_values')
    field_name = models.CharField(max_length=64)
    value = models.JSONField()
    provenance = models.JSONField(default=dict)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['document', 'field_name'], name='unique_document_draft_field')]


class EmailVerificationToken(models.Model):
    PURPOSE_REGISTRATION = "registration"
    PURPOSE_EMAIL_CHANGE = "email_change"
    PURPOSE_CHOICES = [
        (PURPOSE_REGISTRATION, "Registration"),
        (PURPOSE_EMAIL_CHANGE, "Email Change"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verification_tokens",
    )
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    purpose = models.CharField(
        max_length=32,
        choices=PURPOSE_CHOICES,
        default=PURPOSE_REGISTRATION,
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "created_at"]),
            models.Index(fields=["token"]),
        ]

    def __str__(self):
        return f"{self.user.username} {self.purpose} ({self.email})"

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    def can_be_used(self, at_time=None) -> bool:
        from django.utils import timezone

        now = at_time or timezone.now()
        return (not self.is_used) and (self.expires_at > now)

    def mark_used(self, when=None, commit=True):
        from django.utils import timezone

        if self.used_at is not None:
            return self
        self.used_at = when or timezone.now()
        if commit:
            self.save(update_fields=["used_at"])
        return self

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile when User is created"""
    if kwargs.get('raw', False):
        return
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if kwargs.get('raw', False):
        return
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        UserProfile.objects.create(user=instance)
