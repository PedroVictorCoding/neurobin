from django.test import TestCase


class RobotsLoggingTests(TestCase):
    def test_robots_txt_disallows_scraping(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        body = response.content.decode("utf-8")
        self.assertIn("User-agent: *", body)
        self.assertIn("Disallow: /", body)

    def test_robots_queries_emit_to_site_and_robots_loggers(self):
        with self.assertLogs("site_queries", level="INFO") as site_logs:
            with self.assertLogs("robots_queries", level="INFO") as robots_logs:
                self.client.get("/robots.txt")

        self.assertTrue(any("/robots.txt" in row for row in site_logs.output))
        self.assertTrue(any("/robots.txt" in row for row in robots_logs.output))
