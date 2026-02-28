from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone

from compounds.models import Compound
from logs.models import IntakeLog
from stacks.models import Stack, StackItem


class RobotsLoggingTests(TestCase):
    def test_robots_txt_blocks_known_scrapers_but_allows_others(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        body = response.content.decode("utf-8")
        self.assertIn("User-agent: SemrushBot", body)
        self.assertIn("User-agent: AhrefsBot", body)
        self.assertIn("User-agent: MJ12bot", body)
        for token in ("FaviconHash-API", "CensysInspect", "DOMHashBot", "CMS-Checker", "OI-Crawler", "wpbot"):
            self.assertIn(f"User-agent: {token}", body)
        self.assertIn("User-agent: *", body)
        self.assertIn("Allow: /", body)

    @override_settings(
        BOT_BLOCKLIST_UA_SUBSTRINGS=("SemrushBot", "Googlebot"),
        BOT_ALLOWLIST_UA_SUBSTRINGS=("Googlebot",),
    )
    def test_robots_txt_excludes_allowlisted_overlap_from_disallow_entries(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("User-agent: SemrushBot", body)
        self.assertNotIn("User-agent: Googlebot\nDisallow: /", body)

    def test_external_robots_queries_emit_to_site_and_robots_loggers(self):
        with self.assertLogs("site_queries", level="INFO") as site_logs:
            with self.assertLogs("robots_queries", level="INFO") as robots_logs:
                self.client.get(
                    "/robots.txt",
                    REMOTE_ADDR="93.158.71.185",
                    HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                )

        self.assertTrue(any("/robots.txt" in row for row in site_logs.output))
        self.assertTrue(any("/robots.txt" in row for row in robots_logs.output))

    def test_internal_requests_emit_to_internal_logger(self):
        with self.assertLogs("internal_queries", level="INFO") as internal_logs:
            self.client.get("/robots.txt")
        self.assertTrue(any("/robots.txt" in row for row in internal_logs.output))

    def test_bot_requests_emit_to_bot_logger(self):
        with self.assertLogs("bot_queries", level="INFO") as bot_logs:
            self.client.get(
                "/",
                REMOTE_ADDR="54.38.147.75",
                HTTP_USER_AGENT="Mozilla/5.0 (compatible; SemrushBot/7.0; +http://www.semrush.com/bot.html)",
            )
        self.assertTrue(any('"status_code": 403' in row for row in bot_logs.output))

    def test_blocklisted_bot_user_agent_gets_forbidden(self):
        response = self.client.get(
            "/robots.txt",
            HTTP_USER_AGENT="Mozilla/5.0 (compatible; SemrushBot/7.0; +http://www.semrush.com/bot.html)",
            REMOTE_ADDR="54.38.147.75",
        )
        self.assertEqual(response.status_code, 403)

    def test_googlebot_user_agent_is_not_blocked(self):
        response = self.client.get(
            "/robots.txt",
            HTTP_USER_AGENT="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            REMOTE_ADDR="66.249.66.1",
        )
        self.assertEqual(response.status_code, 200)

class ExploitAttemptBlocklistMiddlewareTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_exploit_path_immediately_blocks_ip(self):
        exploit_response = self.client.get("/.env", REMOTE_ADDR="198.51.100.23")
        self.assertEqual(exploit_response.status_code, 403)

        follow_up_response = self.client.get("/about/", REMOTE_ADDR="198.51.100.23")
        self.assertEqual(follow_up_response.status_code, 403)

    def test_block_is_per_ip(self):
        self.client.get("/.env", REMOTE_ADDR="198.51.100.23")
        safe_response = self.client.get("/about/", REMOTE_ADDR="198.51.100.24")
        self.assertEqual(safe_response.status_code, 200)

    def test_localhost_is_not_auto_blocked(self):
        response = self.client.get("/.env", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(response.status_code, 404)

    def test_exploit_attempt_is_logged(self):
        with self.assertLogs("security_queries", level="WARNING") as logs:
            self.client.get("/.env", REMOTE_ADDR="198.51.100.23")
        self.assertTrue(any('"reason": "exploit-path"' in row for row in logs.output))


class HomePageWeekIntakeTests(TestCase):
    def test_home_page_includes_week_intake_preview_for_anonymous_users(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        week_intake = response.context["week_intake"]
        self.assertTrue(week_intake["is_preview"])
        self.assertEqual(len(week_intake["days"]), 7)

    def test_home_page_includes_week_intake_entries_for_authenticated_users(self):
        user = get_user_model().objects.create_user(username="tester", password="pass1234")
        compound = Compound.objects.create(name="Caffeine")
        stack = Stack.objects.create(user=user, name="Morning", is_active=True)
        StackItem.objects.create(
            stack=stack,
            compound=compound,
            intake_time=timezone.now(),
            recurrence_interval=1,
            recurrence_unit="daily",
        )

        self.client.force_login(user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        week_intake = response.context["week_intake"]
        self.assertFalse(week_intake["is_preview"])
        self.assertTrue(week_intake["has_items"])
        self.assertTrue(
            any(
                any(item.compound_name == "Caffeine" for item in day["items"])
                for day in week_intake["days"]
            )
        )

    def test_home_page_week_item_can_be_taken_and_untaken(self):
        user = get_user_model().objects.create_user(username="clicker", password="pass1234")
        compound = Compound.objects.create(name="L-Theanine")
        scheduled_for = timezone.now().replace(microsecond=0)
        stack = Stack.objects.create(user=user, name="Focus", is_active=True)
        item = StackItem.objects.create(
            stack=stack,
            compound=compound,
            intake_time=scheduled_for,
            recurrence_interval=1,
            recurrence_unit="daily",
        )

        self.client.force_login(user)

        take_response = self.client.post(
            "/",
            data={
                "stack_item_id": str(item.id),
                "scheduled_for": scheduled_for.isoformat(),
                "take_stack_item": "1",
            },
        )
        self.assertEqual(take_response.status_code, 302)
        self.assertTrue(
            IntakeLog.objects.filter(
                user=user,
                stack_item=item,
                scheduled_for__isnull=False,
            ).exists()
        )

        untake_response = self.client.post(
            "/",
            data={
                "stack_item_id": str(item.id),
                "scheduled_for": scheduled_for.isoformat(),
                "untake_stack_item": "1",
            },
        )
        self.assertEqual(untake_response.status_code, 302)
        self.assertFalse(
            IntakeLog.objects.filter(
                user=user,
                stack_item=item,
                scheduled_for__isnull=False,
            ).exists()
        )

    def test_home_page_week_item_ajax_toggle_returns_json(self):
        user = get_user_model().objects.create_user(username="async-user", password="pass1234")
        compound = Compound.objects.create(name="Rhodiola")
        scheduled_for = timezone.now().replace(microsecond=0)
        stack = Stack.objects.create(user=user, name="Async", is_active=True)
        item = StackItem.objects.create(
            stack=stack,
            compound=compound,
            intake_time=scheduled_for,
            recurrence_interval=1,
            recurrence_unit="daily",
        )

        self.client.force_login(user)

        take_response = self.client.post(
            "/",
            data={
                "stack_item_id": str(item.id),
                "scheduled_for": scheduled_for.isoformat(),
                "take_stack_item": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(take_response.status_code, 200)
        self.assertEqual(take_response.json(), {"ok": True, "is_taken": True})

        untake_response = self.client.post(
            "/",
            data={
                "stack_item_id": str(item.id),
                "scheduled_for": scheduled_for.isoformat(),
                "untake_stack_item": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(untake_response.status_code, 200)
        self.assertEqual(untake_response.json(), {"ok": True, "is_taken": False})

    def test_home_page_week_items_are_not_truncated_per_day(self):
        user = get_user_model().objects.create_user(username="overflow-user", password="pass1234")
        stack = Stack.objects.create(user=user, name="Overflow", is_active=True)
        scheduled_for = timezone.now().replace(microsecond=0)

        for index in range(5):
            compound = Compound.objects.create(name=f"Overflow Compound {index}")
            StackItem.objects.create(
                stack=stack,
                compound=compound,
                intake_time=scheduled_for,
                recurrence_interval=1,
                recurrence_unit="daily",
            )

        self.client.force_login(user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        day_with_many_items = max(response.context["week_intake"]["days"], key=lambda day: day["count"])
        self.assertGreaterEqual(day_with_many_items["count"], 5)
        self.assertEqual(len(day_with_many_items["items"]), day_with_many_items["count"])
