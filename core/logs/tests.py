from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from compounds.models import (
    Compound,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    Target,
)
from logs.models import IntakeLog


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
