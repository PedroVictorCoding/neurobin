from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
import os

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
