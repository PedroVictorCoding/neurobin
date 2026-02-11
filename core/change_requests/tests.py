from django.contrib.auth.models import User
from django.test import TestCase

from .models import FeatureRequest


class FeatureRequestPageTests(TestCase):
    def test_feature_request_page_renders_for_anonymous_users(self):
        response = self.client.get('/change-requests/feature-request/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Feature / Consideration Request')

    def test_anonymous_user_can_submit_feature_request(self):
        response = self.client.post(
            '/change-requests/feature-request/',
            data={
                'request_type': 'feature',
                'title': 'Stack recommendation presets',
                'details': 'Add one-click goal presets for longevity and cognition.',
                'display_name': 'Anonymous',
                'contact_email': '',
                'source_page': '/home/',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('submitted=1', response['Location'])
        self.assertEqual(FeatureRequest.objects.count(), 1)
        row = FeatureRequest.objects.first()
        self.assertEqual(row.title, 'Stack recommendation presets')
        self.assertIsNone(row.submitted_by)

    def test_authenticated_submission_attaches_user(self):
        user = User.objects.create_user(username='feature_user', password='pw')
        self.client.force_login(user)

        self.client.post(
            '/change-requests/feature-request/',
            data={
                'request_type': 'consideration',
                'title': 'Dose-aware interaction severity',
                'details': 'Show stronger warnings only when overlap windows exist.',
                'display_name': '',
                'contact_email': 'feature@example.com',
                'source_page': '/logs/analytics/',
            },
        )
        row = FeatureRequest.objects.get()
        self.assertEqual(row.submitted_by_id, user.id)
        self.assertEqual(row.request_type, 'consideration')
