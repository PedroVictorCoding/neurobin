from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class RegistrationTests(TestCase):
    def test_registration_requires_email(self):
        response = self.client.post(
            reverse("register"),
            data={
                "username": "noemailuser",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email")
        self.assertFalse(User.objects.filter(username="noemailuser").exists())

    def test_registration_saves_email(self):
        response = self.client.post(
            reverse("register"),
            data={
                "username": "emailuser",
                "email": "emailuser@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="emailuser")
        self.assertEqual(user.email, "emailuser@example.com")
