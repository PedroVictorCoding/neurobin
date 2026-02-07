from django.db import models
from django.contrib.auth.models import User

# keep default User model; add minimal profile if needed
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
