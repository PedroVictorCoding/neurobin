from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from compounds.models import (
    Compound,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    Target,
)
from logs.models import IntakeLog, RequestIPPathStat, RequestIPProfile


class AnalyticsDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dash_user", password="pw")
        self.client.force_login(self.user)
        self.now = timezone.now()

    def test_dashboard_deduplicates_todays_compounds_and_builds_inferred_pairs(self):
        compound_a = Compound.objects.create(name="Compound A")
        compound_b = Compound.objects.create(name="Compound B")
        target = Target.objects.create(name="CYP3A4")

        # Duplicate intake entries for the same compound should collapse into one chip with count.
        IntakeLog.objects.create(user=self.user, compound=compound_a, taken_at=self.now, amount="10", unit="mg")
        IntakeLog.objects.create(user=self.user, compound=compound_a, taken_at=self.now, amount="5", unit="mg")
        IntakeLog.objects.create(user=self.user, compound=compound_b, taken_at=self.now, amount="20", unit="mg")

        CompoundTargetInteraction.objects.create(
            compound=compound_a,
            target=target,
            mechanism="substrate",
            source="test",
        )
        CompoundTargetInteraction.objects.create(
            compound=compound_b,
            target=target,
            mechanism="inhibitor",
            source="test",
        )

        response = self.client.get("/logs/analytics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["todays_compounds"]), 2)
        self.assertEqual(len(response.context["todays_compound_rows"]), 2)
        counts = {row["compound"].id: row["count"] for row in response.context["todays_compound_rows"]}
        self.assertEqual(counts[compound_a.id], 2)
        self.assertEqual(counts[compound_b.id], 1)
        self.assertEqual(response.context["todays_known_pair_count"], 0)
        self.assertGreaterEqual(response.context["todays_inferred_pair_count"], 1)
        self.assertEqual(response.context["todays_possible_pair_count"], 1)
        self.assertEqual(response.context["todays_unresolved_pair_count"], 0)

    def test_dashboard_shows_documented_pair_summary(self):
        compound_a = Compound.objects.create(name="Compound C")
        compound_b = Compound.objects.create(name="Compound D")
        target = Target.objects.create(name="5-HT2A receptor")

        IntakeLog.objects.create(user=self.user, compound=compound_a, taken_at=self.now, amount="10", unit="mg")
        IntakeLog.objects.create(user=self.user, compound=compound_b, taken_at=self.now, amount="15", unit="mg")

        CompoundToCompoundTargetInteraction.objects.create(
            compound_a=compound_a,
            compound_b=compound_b,
            target=target,
            interaction_type="competitive",
            description="Documented test interaction",
            confidence="high",
            source="test",
        )

        response = self.client.get("/logs/analytics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["todays_known_pair_count"], 1)
        self.assertEqual(len(response.context["todays_known_pair_summaries"]), 1)
        self.assertEqual(response.context["todays_inferred_pair_count"], 0)


@override_settings(ABUSEIPDB_AUTO_ENRICH_NEW_IPS=False, ABUSE_THROTTLE_ENABLED=False)
class RequestIPTrackingTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_site_query_tracking_creates_profile_and_path_stat(self):
        response = self.client.get(
            "/about/",
            REMOTE_ADDR="198.51.100.42",
            HTTP_USER_AGENT="Mozilla/5.0 (X11; Linux x86_64)",
        )
        self.assertEqual(response.status_code, 200)

        profile = RequestIPProfile.objects.get(ip_address="198.51.100.42")
        self.assertEqual(profile.total_requests, 1)
        self.assertEqual(profile.get_requests, 1)
        self.assertEqual(profile.post_requests, 0)
        self.assertEqual(profile.distinct_paths, 1)
        self.assertEqual(profile.last_path, "/about/")

        path_stat = RequestIPPathStat.objects.get(ip_profile=profile, method="GET", path="/about/")
        self.assertEqual(path_stat.request_count, 1)


@override_settings(ABUSEIPDB_AUTO_ENRICH_NEW_IPS=False, ABUSE_THROTTLE_ENABLED=False)
class IPAnalyticsDashboardAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="normal", password="pw")
        self.staff = User.objects.create_user(username="staff", password="pw", is_staff=True)

    def test_non_staff_is_redirected(self):
        self.client.force_login(self.user)
        response = self.client.get("/logs/ip-analytics/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_staff_can_access_dashboard(self):
        self.client.force_login(self.staff)
        response = self.client.get("/logs/ip-analytics/")
        self.assertEqual(response.status_code, 200)


@override_settings(
    ABUSEIPDB_AUTO_ENRICH_NEW_IPS=False,
    ABUSE_THROTTLE_ENABLED=True,
    ABUSE_THROTTLE_CONFIDENCE_THRESHOLD=50,
    ABUSE_THROTTLE_BASE_LIMIT_PER_HOUR=5,
    ABUSE_THROTTLE_STEP_PERCENT=10,
    ABUSE_THROTTLE_STEP_REDUCTION=1,
    ABUSE_THROTTLE_MIN_LIMIT_PER_HOUR=0,
)
class AbuseThrottleMiddlewareTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        now = timezone.now()
        # 83% -> limit becomes 2/hour with the default formula.
        RequestIPProfile.objects.create(
            ip_address="198.51.100.77",
            first_seen_at=now,
            last_seen_at=now,
            abuse_checked_at=now,
            abuse_confidence_score=83,
            is_throttle_active=True,
            throttle_limit_per_hour=2,
        )

    def test_abusive_ip_is_rate_limited(self):
        first = self.client.get("/about/", REMOTE_ADDR="198.51.100.77", HTTP_USER_AGENT="Mozilla/5.0")
        second = self.client.get("/about/", REMOTE_ADDR="198.51.100.77", HTTP_USER_AGENT="Mozilla/5.0")
        third = self.client.get("/about/", REMOTE_ADDR="198.51.100.77", HTTP_USER_AGENT="Mozilla/5.0")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third["X-RateLimit-Limit"], "2")

    def test_zero_per_hour_limit_fully_blocks_ip(self):
        now = timezone.now()
        RequestIPProfile.objects.create(
            ip_address="198.51.100.78",
            first_seen_at=now,
            last_seen_at=now,
            abuse_checked_at=now,
            abuse_confidence_score=100,
            is_throttle_active=True,
            throttle_limit_per_hour=0,
        )

        response = self.client.get("/about/", REMOTE_ADDR="198.51.100.78", HTTP_USER_AGENT="Mozilla/5.0")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["X-RateLimit-Limit"], "0")
