import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import digest  # noqa: E402

NOW = datetime(2026, 11, 22, 7, 0, 0, tzinfo=timezone.utc)
DATA = {
    "last_updated": "2026-11-22 06:55 UTC",
    "generated_at": "2026-11-22T06:55:00Z",
    "top_stories": [
        {"title": "Chip <b>launch</b> & more | pipe", "sector": "Semiconductors", "link": "https://example.com/a?utm_source=x",
         "summary": "A <script>x</script> summary.", "why_it_matters": "It matters."},
        {"title": "Bad link story", "sector": "AI", "link": "javascript:alert(1)", "summary": "", "why_it_matters": ""},
    ],
    "emerging": [{"term": "rubin platform"}],
    "weekly_recap": {"text": "The week in review.", "week_ending": "2026-11-22"},
}


class DigestTests(unittest.TestCase):
    def test_slack_text_is_escaped_and_links_are_safe(self):
        text = digest.build_slack_text(DATA, "https://site.example/", NOW)
        self.assertIn("<https://example.com/a|", text)  # tracking param stripped
        self.assertNotIn("utm_", text)
        self.assertIn("&lt;b&gt;", text)
        self.assertNotIn("javascript:", text)
        self.assertIn("Emerging:* rubin platform", text)
        self.assertIn("Weekly recap:* The week in review.", text)
        self.assertIn("Open the dashboard", text)

    def test_recap_only_on_its_own_day(self):
        later = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
        self.assertNotIn("Weekly recap", digest.build_slack_text(DATA, "", later))

    def test_email_html_is_escaped(self):
        subject, plain, rich = digest.build_email(DATA, "", NOW)
        self.assertTrue(subject.startswith("Tech Insights: Chip"))
        self.assertNotIn("<script>", rich)
        self.assertIn("&lt;b&gt;launch&lt;/b&gt;", rich)
        self.assertNotIn("javascript:", rich + plain)
        self.assertIn("Why it matters: It matters.", plain)

    def test_stale_data_gets_a_warning(self):
        late = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
        self.assertIn("hours old", digest.build_slack_text(DATA, "", late))
        self.assertNotIn("hours old", digest.build_slack_text(DATA, "", NOW))

    def test_webhook_must_be_https(self):
        with self.assertRaises(ValueError):
            digest.send_slack("http://hooks.example.com/x", "hi")
        with self.assertRaises(ValueError):
            digest.send_slack("file:///etc/passwd", "hi")


if __name__ == "__main__":
    unittest.main()
