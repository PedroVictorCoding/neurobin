from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from stacks.models import Stack
from logs.models import BloodworkEntry, BloodworkMeasurement, UserGoal, UserGoalCompletion
from accounts.models import EmailVerificationToken


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_DELIVERY_ASYNC=False,
    EMAIL_VERIFICATION_TOKEN_TTL_HOURS=24,
)
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

    def test_registration_creates_inactive_user_and_sends_verification_email(self):
        response = self.client.post(
            reverse("register"),
            data={
                "username": "emailuser",
                "email": "emailuser@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertRedirects(response, reverse("verify_email_sent"))
        user = User.objects.get(username="emailuser")
        self.assertEqual(user.email, "emailuser@example.com")
        self.assertFalse(user.is_active)
        token = EmailVerificationToken.objects.get(user=user, purpose=EmailVerificationToken.PURPOSE_REGISTRATION)
        self.assertEqual(token.email, user.email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(token.token), mail.outbox[0].body)
        self.assertIn("verify your", mail.outbox[0].subject.lower())

    def test_registration_rejects_duplicate_email(self):
        User.objects.create_user(
            username="first",
            email="existing@example.com",
            password="StrongPass123!",
        )
        response = self.client.post(
            reverse("register"),
            data={
                "username": "second",
                "email": "existing@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account with this email already exists.")
        self.assertFalse(User.objects.filter(username="second").exists())

    def test_verify_email_activates_account(self):
        user = User.objects.create_user(
            username="verify_user",
            email="verify@example.com",
            password="StrongPass123!",
            is_active=False,
        )
        token = EmailVerificationToken.objects.create(
            user=user,
            email=user.email,
            purpose=EmailVerificationToken.PURPOSE_REGISTRATION,
            expires_at=timezone.now() + timedelta(hours=2),
        )

        response = self.client.get(reverse("verify_email", kwargs={"token": token.token}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email verified")
        user.refresh_from_db()
        token.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNotNone(token.used_at)

    def test_verify_email_rejects_expired_token(self):
        user = User.objects.create_user(
            username="expired_user",
            email="expired@example.com",
            password="StrongPass123!",
            is_active=False,
        )
        token = EmailVerificationToken.objects.create(
            user=user,
            email=user.email,
            purpose=EmailVerificationToken.PURPOSE_REGISTRATION,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get(reverse("verify_email", kwargs={"token": token.token}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid or expired")
        user.refresh_from_db()
        token.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertIsNone(token.used_at)


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


class ProfileDashboardGoalTrackerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="goalowner",
            email="goalowner@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="goalviewer",
            email="goalviewer@example.com",
            password="StrongPass123!",
        )

    def test_owner_can_add_weekly_goal(self):
        self.client.login(username="goalowner", password="StrongPass123!")

        response = self.client.post(
            reverse("profile_dashboard"),
            data={
                "action": "add_profile_goal",
                "goal_name": "Morning walk",
                "goal_type": "health",
            },
        )

        self.assertRedirects(response, f"{reverse('profile_dashboard')}?tab=goals")
        goal = UserGoal.objects.get(user=self.user)
        self.assertEqual(goal.name, "Morning walk")
        self.assertEqual(goal.goal_type, "health")

    def test_owner_can_toggle_goal_completion(self):
        goal = UserGoal.objects.create(user=self.user, name="Lift", goal_type="workout")
        self.client.login(username="goalowner", password="StrongPass123!")
        today = timezone.localdate().isoformat()

        response = self.client.post(
            reverse("profile_dashboard"),
            data={
                "action": "toggle_goal_completion",
                "goal_id": str(goal.id),
                "goal_date": today,
                "is_completed": "1",
            },
        )

        self.assertRedirects(response, f"{reverse('profile_dashboard')}?tab=goals")
        completion = UserGoalCompletion.objects.get(goal=goal, date=timezone.localdate())
        self.assertTrue(completion.completed)

    def test_non_owner_cannot_modify_goal_data(self):
        goal = UserGoal.objects.create(user=self.user, name="Protected goal", goal_type="health")
        self.client.login(username="goalviewer", password="StrongPass123!")

        response = self.client.post(
            reverse("user_profile", kwargs={"username": "goalowner"}),
            data={
                "action": "toggle_goal_completion",
                "goal_id": str(goal.id),
                "goal_date": timezone.localdate().isoformat(),
                "is_completed": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserGoalCompletion.objects.filter(goal=goal).exists())


class ProfileDashboardBloodworkTabTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bloodowner",
            email="bloodowner@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="bloodviewer",
            email="bloodviewer@example.com",
            password="StrongPass123!",
        )

    def test_owner_profile_can_view_bloodwork_tab(self):
        entry = BloodworkEntry.objects.create(
            user=self.user,
            collected_at=timezone.now(),
            panel_name="CBC",
            lab_name="Labcorp",
            notes="Routine check",
        )
        BloodworkMeasurement.objects.create(
            entry=entry,
            marker_name="Ferritin",
            value="72.5",
            unit="ng/mL",
            display_order=0,
        )

        self.client.login(username="bloodowner", password="StrongPass123!")
        response = self.client.get(f"{reverse('profile_dashboard')}?tab=bloodwork")

        self.assertEqual(response.context["active_tab"], "bloodwork")
        self.assertContains(response, "Manage Bloodwork")
        self.assertContains(response, "CBC")
        self.assertContains(response, "Ferritin")

    def test_other_profile_does_not_show_bloodwork_tab(self):
        BloodworkEntry.objects.create(
            user=self.user,
            collected_at=timezone.now(),
            panel_name="CMP",
        )

        self.client.login(username="bloodviewer", password="StrongPass123!")
        response = self.client.get(reverse("user_profile", kwargs={"username": "bloodowner"}))

        self.assertNotContains(response, "Manage Bloodwork")
        self.assertNotContains(response, "Bloodwork History")
