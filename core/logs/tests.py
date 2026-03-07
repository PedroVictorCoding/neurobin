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
from logs.models import (
    BloodworkEntry,
    BloodworkMeasurement,
    BloodworkRelatedIntake,
    IntakeLog,
    RequestIPPathStat,
    RequestIPProfile,
)


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


class BloodworkDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="blood_user", password="pw")
        self.client.force_login(self.user)
        self.compound = Compound.objects.create(name="Magnesium")
        self.intake_log = IntakeLog.objects.create(
            user=self.user,
            compound=self.compound,
            taken_at=timezone.now(),
            amount="200",
            unit="mg",
            notes="Evening dose",
        )

    def test_user_can_create_bloodwork_panel_linked_to_intake_logs(self):
        response = self.client.get("/logs/bloodwork/")
        self.assertEqual(response.status_code, 200)

        payload = {
            "collected_at": "2026-03-01T08:30",
            "panel_name": "Lipid Panel",
            "lab_name": "Quest",
            "notes": "Fasted 12 hours",
            "related_intake_logs": [str(self.intake_log.id)],
            "measurements-TOTAL_FORMS": "1",
            "measurements-INITIAL_FORMS": "0",
            "measurements-MIN_NUM_FORMS": "0",
            "measurements-MAX_NUM_FORMS": "1000",
            "measurements-0-marker_name": "LDL",
            "measurements-0-value": "112",
            "measurements-0-unit": "mg/dL",
            "measurements-0-reference_low": "0",
            "measurements-0-reference_high": "99",
            "measurements-0-notes": "Flagged high",
        }

        response = self.client.post("/logs/bloodwork/", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("bloodwork/?created=1", response["Location"])

        entry = BloodworkEntry.objects.get(user=self.user)
        self.assertEqual(entry.panel_name, "Lipid Panel")
        self.assertEqual(entry.lab_name, "Quest")
        self.assertEqual(entry.notes, "Fasted 12 hours")

        measurement = BloodworkMeasurement.objects.get(entry=entry)
        self.assertEqual(measurement.marker_name, "LDL")
        self.assertEqual(str(measurement.value), "112.000")
        self.assertEqual(measurement.unit, "mg/dL")

        relation = BloodworkRelatedIntake.objects.get(entry=entry)
        self.assertEqual(relation.intake_log, self.intake_log)


class BloodworkEditDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="edit_user", password="pw")
        self.other = User.objects.create_user(username="other_user", password="pw")
        self.client.force_login(self.user)
        self.compound = Compound.objects.create(name="Zinc")
        self.entry = BloodworkEntry.objects.create(
            user=self.user,
            collected_at=timezone.now(),
            panel_name="Hormone Panel",
            lab_name="LabCorp",
        )
        BloodworkMeasurement.objects.create(
            entry=self.entry,
            marker_name="Total Testosterone",
            value="650",
            unit="ng/dL",
            reference_low="348",
            reference_high="1197",
        )

    def _post_payload(self, marker_name="LDL", value="112"):
        return {
            "collected_at": "2026-03-01T09:00",
            "panel_name": "Lipid Panel",
            "lab_name": "Quest",
            "notes": "",
            "measurements-TOTAL_FORMS": "1",
            "measurements-INITIAL_FORMS": "0",
            "measurements-MIN_NUM_FORMS": "0",
            "measurements-MAX_NUM_FORMS": "1000",
            "measurements-0-marker_name": marker_name,
            "measurements-0-value": value,
            "measurements-0-unit": "mg/dL",
            "measurements-0-reference_low": "",
            "measurements-0-reference_high": "",
            "measurements-0-notes": "",
        }

    def test_edit_view_loads_existing_data(self):
        response = self.client.get(f"/logs/bloodwork/{self.entry.id}/edit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hormone Panel")
        self.assertContains(response, "Total Testosterone")

    def test_edit_updates_measurements(self):
        payload = self._post_payload(marker_name="LDL Cholesterol", value="95")
        response = self.client.post(f"/logs/bloodwork/{self.entry.id}/edit/", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("?updated=1", response["Location"])

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.panel_name, "Lipid Panel")
        measurements = list(self.entry.measurements.all())
        self.assertEqual(len(measurements), 1)
        self.assertEqual(measurements[0].marker_name, "LDL Cholesterol")
        self.assertEqual(str(measurements[0].value), "95.000")

    def test_edit_requires_at_least_one_measurement(self):
        payload = {
            "collected_at": "2026-03-01T09:00",
            "panel_name": "Empty Panel",
            "measurements-TOTAL_FORMS": "1",
            "measurements-INITIAL_FORMS": "0",
            "measurements-MIN_NUM_FORMS": "0",
            "measurements-MAX_NUM_FORMS": "1000",
            "measurements-0-marker_name": "",
            "measurements-0-value": "",
        }
        response = self.client.post(f"/logs/bloodwork/{self.entry.id}/edit/", data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least one")

    def test_delete_removes_entry(self):
        response = self.client.post(f"/logs/bloodwork/{self.entry.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("?deleted=1", response["Location"])
        self.assertEqual(BloodworkEntry.objects.filter(user=self.user).count(), 0)

    def test_delete_cascades_to_measurements(self):
        self.client.post(f"/logs/bloodwork/{self.entry.id}/delete/")
        self.assertEqual(BloodworkMeasurement.objects.count(), 0)

    def test_delete_requires_ownership(self):
        self.client.force_login(self.other)
        response = self.client.post(f"/logs/bloodwork/{self.entry.id}/delete/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(BloodworkEntry.objects.count(), 1)

    def test_edit_requires_ownership(self):
        self.client.force_login(self.other)
        response = self.client.get(f"/logs/bloodwork/{self.entry.id}/edit/")
        self.assertEqual(response.status_code, 404)


