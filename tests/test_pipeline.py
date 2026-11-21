"""End-to-end pipeline test with a fake feedparser and a fake Gemini client (no network)."""
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_data as fd  # noqa: E402
import insights as ins  # noqa: E402

NOW_ISO = "2026-11-22T12:00:00Z"  # a Sunday


class FakeParsed(dict):
    def __init__(self, entries=(), **kw):
        super().__init__(**kw)
        self.entries = list(entries)


def struct(hours_ago):
    t = ins.parse_iso(NOW_ISO).timestamp() - hours_ago * 3600
    return time.gmtime(t)


def entry(title, link, hours_ago=2, summary="A reasonably long description of the story with real detail in it."):
    return {"title": title, "link": link, "published_parsed": struct(hours_ago), "summary": summary}


FEEDS = {
    "https://huggingface.co/blog/feed.xml": FakeParsed([
        entry("Rubin platform ships to hyperscalers", "https://hf.co/a?utm_source=x"),
        entry("<script>alert(1)</script>Evil title", "javascript:alert(1)"),  # bad link -> dropped
        entry("Empty text story", "https://hf.co/c", summary=""),
    ]),
    "https://semiengineering.com/feed/": FakeParsed([
        entry("Hyperscalers order Rubin platform racks", "https://se.com/b"),
    ]),
    "https://www.techmeme.com/feed.xml": FakeParsed([
        entry("Rubin platform memory design explained", "https://tm.com/c"),
    ]),
    "https://www.therobotreport.com/feed/": FakeParsed(bozo=1, entries=[]),
    "https://spacenews.com/feed/": FakeParsed(status=503),
}


def fake_parse(url, agent=None):
    return FEEDS.get(url, FakeParsed())  # unknown feeds are "empty"


class FakeGemini:
    available = True
    model = "fake"
    errors = []
    calls = 0

    def __init__(self, enabled=True):
        pass

    def generate_json(self, prompt, attempts=3):
        FakeGemini.calls += 1
        if "ITEMS:" in prompt:
            items = json.loads(prompt.split("ITEMS:\n", 1)[1])
            return json.dumps([
                {"id": i["id"], "summary": f"Summary of {i['title'][:40]} with detail.", "why_it_matters": "Matters a lot.", "importance": 7}
                for i in items
            ])
        if "DEVELOPMENTS:" in prompt:
            return json.dumps([{"ticker": "NVDA", "company": "NVIDIA", "impact_blurb": "Could gain."}])
        if "STORIES:" in prompt:
            return json.dumps({"text": "This week the Rubin platform dominated coverage across several outlets.", "themes": ["Chips"]})
        return None


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        FakeGemini.calls = 0
        patches = [
            mock.patch.object(fd, "DATA_FILE", self.tmp / "data.json"),
            mock.patch.object(fd, "STATE_FILE", self.tmp / "state" / "items.json"),
            mock.patch.object(fd, "ARCHIVE_DIR", self.tmp / "archive"),
            mock.patch.dict(os.environ, {"PIPELINE_NOW": NOW_ISO}),
            mock.patch.dict(sys.modules, {"feedparser": types.SimpleNamespace(parse=fake_parse)}),
            mock.patch.object(fd, "Gemini", FakeGemini),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_it(self, **kw):
        return fd.run_pipeline(**kw)

    def test_full_run(self):
        data = self.run_it()
        self.assertEqual(data["version"], 2)
        ai = [i for i in data["sectors"]["AI"]]
        titles = [i["title"] for i in ai]
        self.assertEqual(len(ai), 2)  # malicious-link entry dropped
        self.assertFalse(any("script" in t.lower() for t in titles))
        for item in ai:
            self.assertEqual(item["summary_source"], "ai")
            self.assertNotIn("utm_", item["link"])
        # Cross-feed duplicate coverage is collected into "related" on a primary item.
        self.assertTrue(data["top_stories"])
        self.assertEqual(data["stock_watch"][0]["ticker"], "NVDA")
        self.assertIsNotNone(data["stock_watch_generated_at"])
        self.assertIn("Rubin", data["weekly_recap"]["text"])  # Sunday -> recap generated
        self.assertEqual(data["weekly_recap"]["week_ending"], "2026-11-22")
        problems = {(h["source"], h["status"]) for h in data["health"]["feeds"] if h["status"] != "ok"}
        self.assertIn(("The Robot Report", "error"), problems)
        self.assertIn(("SpaceNews", "error"), problems)
        self.assertTrue(any("feed(s) returned no items" in n for n in data["notices"]))
        # Files written
        self.assertTrue((self.tmp / "data.json").exists())
        self.assertTrue((self.tmp / "state" / "items.json").exists())
        self.assertEqual(json.loads((self.tmp / "archive" / "index.json").read_text())["dates"], ["2026-11-22"])

    def test_emerging_waits_for_history_then_appears(self):
        self.assertEqual(self.run_it()["emerging"], [])  # no archive yet
        # Three earlier days of unrelated snapshots provide a baseline.
        for day in ("2026-11-19", "2026-11-20", "2026-11-21"):
            fd.save_json(self.tmp / "archive" / f"{day}.json", {"date": day, "sectors": {}, "top_stories": []})
        terms = [e["term"] for e in self.run_it()["emerging"]]
        self.assertTrue(any("rubin" in t for t in terms), terms)

    def test_second_run_does_not_resummarise(self):
        self.run_it()
        first_calls = FakeGemini.calls
        self.run_it()
        # Only stock/recap may call again (and they are throttled); item summaries must not.
        self.assertLessEqual(FakeGemini.calls - first_calls, 0)

    def test_no_ai_falls_back_to_feed_text_and_never_ellipsis(self):
        class Off(FakeGemini):
            available = False
            errors = ["GEMINI_API_KEY is not set"]

        with mock.patch.object(fd, "Gemini", Off):
            data = self.run_it()
        for items in data["sectors"].values():
            for item in items:
                self.assertNotEqual(item["summary"].strip(), "...")
        by_title = {i["title"]: i for i in data["sectors"]["AI"]}
        self.assertEqual(by_title["Empty text story"]["summary"], "")
        self.assertEqual(by_title["Empty text story"]["summary_source"], "none")
        self.assertEqual(by_title["Rubin platform ships to hyperscalers"]["summary_source"], "feed")
        self.assertTrue(any("AI summaries are unavailable" in n for n in data["notices"]))
        self.assertEqual(data["stock_watch"], [])

    def test_items_stay_over_a_weekend_when_feeds_go_quiet(self):
        self.run_it()
        FEEDS_BACKUP = dict(FEEDS)
        try:
            for url in list(FEEDS):
                FEEDS[url] = FakeParsed()  # every feed now empty (like arXiv on a Saturday)
            with mock.patch.dict(os.environ, {"PIPELINE_NOW": "2026-11-23T12:00:00Z"}):
                data = self.run_it()
        finally:
            FEEDS.update(FEEDS_BACKUP)
        # All feeds "empty" (not errored) -> run continues and keeps yesterday's items.
        self.assertTrue(data["sectors"]["AI"])

    def test_all_feeds_failing_leaves_existing_data(self):
        self.run_it()
        before = (self.tmp / "data.json").read_text()
        with mock.patch.dict(sys.modules, {"feedparser": types.SimpleNamespace(parse=lambda *a, **k: FakeParsed(status=500))}):
            self.assertIsNone(self.run_it())
        self.assertEqual((self.tmp / "data.json").read_text(), before)

    def test_dry_run_writes_nothing(self):
        self.run_it(write=False)
        self.assertFalse((self.tmp / "data.json").exists())

    def test_old_schema_recap_string_is_preserved(self):
        (self.tmp / "data.json").write_text(json.dumps({"weekly_recap": "Old recap text from the previous schema."}))
        with mock.patch.dict(os.environ, {"PIPELINE_NOW": "2026-11-23T12:00:00Z"}):  # Monday: no new recap
            data = self.run_it()
        self.assertEqual(data["weekly_recap"]["text"], "Old recap text from the previous schema.")


if __name__ == "__main__":
    unittest.main()
