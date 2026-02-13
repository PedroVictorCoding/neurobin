from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from stacks.models import Stack


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


class ProfileDashboardStackToggleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="profileowner",
            email="owner@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="StrongPass123!",
        )

    def test_profile_post_can_activate_stack(self):
        stack = Stack.objects.create(user=self.user, name="Activation Stack", is_active=False)
        self.client.login(username="profileowner", password="StrongPass123!")

        response = self.client.post(
            reverse("profile_dashboard"),
            data={
                "action": "set_stack_active",
                "stack_id": str(stack.id),
                "is_active": "1",
            },
        )

        self.assertRedirects(response, f"{reverse('profile_dashboard')}?tab=stacks")
        stack.refresh_from_db()
        self.assertTrue(stack.is_active)

    def test_profile_post_can_deactivate_stack(self):
        stack = Stack.objects.create(user=self.user, name="Deactivation Stack", is_active=True)
        self.client.login(username="profileowner", password="StrongPass123!")

        response = self.client.post(
            reverse("profile_dashboard"),
            data={
                "action": "set_stack_active",
                "stack_id": str(stack.id),
            },
        )

        self.assertRedirects(response, f"{reverse('profile_dashboard')}?tab=stacks")
        stack.refresh_from_db()
        self.assertFalse(stack.is_active)

    def test_other_profile_post_does_not_toggle(self):
        stack = Stack.objects.create(user=self.user, name="Protected Stack", is_active=False)
        self.client.login(username="viewer", password="StrongPass123!")

        response = self.client.post(
            reverse("user_profile", kwargs={"username": "profileowner"}),
            data={
                "action": "set_stack_active",
                "stack_id": str(stack.id),
                "is_active": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        stack.refresh_from_db()
        self.assertFalse(stack.is_active)
