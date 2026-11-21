import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import insights as ins  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)  # a Sunday


def iso(hours_ago):
    return ins.to_iso(NOW - timedelta(hours=hours_ago))


def make(title, source="Src", sector="AI", hours_ago=1, importance=5, weight=1.0, link=None, summary=""):
    link = link or f"https://example.com/{abs(hash((title, source)))}"
    return {
        "id": ins.item_id(link), "title": title, "source": source, "sector": sector, "link": link,
        "published": iso(hours_ago), "first_seen": iso(hours_ago), "importance": importance,
        "weight": weight, "summary": summary, "related": [],
    }


class CleaningTests(unittest.TestCase):
    def test_strips_tags_entities_and_whitespace(self):
        self.assertEqual(ins.clean_html("<p>Hello &amp; <b>welcome</b>\n  friends</p>"), "Hello & welcome friends")

    def test_escaped_script_tags_are_removed(self):
        self.assertNotIn("<", ins.clean_html("&lt;script&gt;alert(1)&lt;/script&gt;ok"))

    def test_arxiv_and_wordpress_boilerplate(self):
        text = "arXiv:2611.01234v1 Announce Type: new Abstract: We study X."
        self.assertEqual(ins.clean_html(text), "We study X.")
        wp = "Great news. The post Great news appeared first on Example Blog."
        self.assertEqual(ins.clean_html(wp), "Great news.")

    def test_trailing_read_more_removed(self):
        self.assertEqual(ins.clean_html("A story about chips [&#8230;]"), "A story about chips")

    def test_fallback_summary_never_returns_bare_ellipsis(self):
        self.assertEqual(ins.fallback_summary("", "Title"), "")
        self.assertEqual(ins.fallback_summary("Title", "Title"), "")
        self.assertEqual(ins.fallback_summary("short", "T"), "")

    def test_fallback_summary_takes_first_two_sentences(self):
        text = "The first sentence is long enough to count. The second adds detail here. A third should be dropped."
        out = ins.fallback_summary(text, "x")
        self.assertIn("second adds detail", out)
        self.assertNotIn("third", out)

    def test_fallback_summary_truncates_very_long_sentence(self):
        out = ins.fallback_summary("word " * 200, "x", max_len=100)
        self.assertLessEqual(len(out), 101)
        self.assertTrue(out.endswith("…"))


class LinkTests(unittest.TestCase):
    def test_rejects_non_http_schemes(self):
        for bad in ("javascript:alert(1)", "data:text/html,hi", "ftp://x.com/a", "//x.com", "", None, 5):
            self.assertIsNone(ins.safe_link(bad), bad)

    def test_strips_tracking_params_and_fragment(self):
        out = ins.safe_link("https://Example.com/a?utm_source=x&id=7&fbclid=z#frag")
        self.assertEqual(out, "https://Example.com/a?id=7")

    def test_id_ignores_www_trailing_slash_and_tracking(self):
        a = ins.item_id(ins.safe_link("https://www.example.com/story/?utm_medium=rss"))
        b = ins.item_id(ins.safe_link("https://example.com/story"))
        self.assertEqual(a, b)


class SimilarityTests(unittest.TestCase):
    def test_same_story_different_wording(self):
        self.assertTrue(similar := ins.similar("Nvidia unveils new Rubin AI chip for data centers",
                                               "Nvidia unveils Rubin AI chip for data centers"))
        self.assertTrue(similar)

    def test_different_stories(self):
        self.assertFalse(ins.similar("Nvidia unveils new Rubin AI chip", "Quantum startup raises Series B funding"))

    def test_short_titles_need_exact_match(self):
        self.assertFalse(ins.similar("Chips", "Chip makers"))

    def test_cluster_merges_and_lists_related_without_mutating_input(self):
        a = make("Nvidia unveils Rubin AI chip for data centers", source="EE Times", weight=1.0, importance=7)
        b = make("Nvidia unveils new Rubin AI chip for data centers", source="Techmeme", weight=0.9, importance=6)
        c = make("Quantum startup raises Series B funding round", source="Crunchbase")
        out = ins.cluster_items([b, a, c])
        self.assertEqual(len(out), 2)
        primary = next(i for i in out if i["source"] == "EE Times")
        self.assertEqual([r["source"] for r in primary["related"]], ["Techmeme"])
        self.assertEqual(a["related"], [])  # inputs untouched

    def test_cluster_does_not_list_same_source_as_related(self):
        a = make("Nvidia unveils Rubin AI chip for data centers", source="EE Times")
        b = make("Nvidia unveils Rubin AI chip for data centers today", source="EE Times")
        out = ins.cluster_items([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["related"], [])


class RankingTests(unittest.TestCase):
    def test_importance_and_recency_both_matter(self):
        big_old = make("Big but old", importance=9, hours_ago=120)
        small_new = make("Small but new", importance=4, hours_ago=1)
        big_new = make("Big and new", importance=9, hours_ago=2)
        ranked = ins.rank_items([big_old, small_new, big_new], NOW)
        self.assertEqual(ranked[0]["title"], "Big and new")
        self.assertEqual(ranked[-1]["title"], "Big but old")

    def test_source_weight_lowers_papers(self):
        paper = make("A paper", importance=8, weight=0.5)
        news = make("A news story", importance=8, weight=1.0)
        self.assertEqual(ins.rank_items([paper, news], NOW)[0]["title"], "A news story")

    def test_corroboration_bonus(self):
        solo = make("Solo story alpha", importance=5)
        backed = make("Backed story beta", importance=5)
        backed["related"] = [{"source": "A"}, {"source": "B"}]
        self.assertEqual(ins.rank_items([solo, backed], NOW)[0]["title"], "Backed story beta")

    def test_missing_importance_uses_default(self):
        item = make("No rating", importance=None)
        self.assertGreater(ins.score_item(item, NOW), 0)

    def test_top_stories_limit_per_sector_and_dedupe(self):
        headlines = [
            "Anthropic ships agent framework update for developers",
            "Mistral releases open weights model family",
            "OpenAI cuts API pricing for reasoning models",
            "Google adds on-device translation to Pixel phones",
        ]
        ai = [make(h, sector="AI", importance=9 - n) for n, h in enumerate(headlines)]
        dup = make("Mistral releases open weights model family", sector="Policy", importance=9, source="Other")
        space = make("Rocket launch lifts new satellite constellation", sector="Space", importance=3)
        sectors = {"AI": ins.rank_items(ai, NOW), "Policy": ins.rank_items([dup], NOW), "Space": ins.rank_items([space], NOW)}
        top = ins.pick_top_stories(sectors, NOW, n=5, per_sector=2)
        self.assertEqual(sum(1 for t in top if t["sector"] == "AI"), 2)
        titles = [t["title"] for t in top]
        self.assertEqual(len([t for t in titles if "Mistral" in t]), 1)  # duplicate dropped
        self.assertIn("Rocket launch lifts new satellite constellation", titles)

    def test_top_stories_skip_stale_items(self):
        stale = make("Ancient news story about satellites", hours_ago=200, importance=10)
        sectors = {"Space": ins.rank_items([stale], NOW)}
        self.assertEqual(ins.pick_top_stories(sectors, NOW), [])


class EmergingTests(unittest.TestCase):
    def items(self):
        return [
            make("Rubin platform ships to hyperscalers", source="EE Times", sector="Semiconductors"),
            make("Hyperscalers order Rubin platform racks", source="Techmeme", sector="Breaking"),
            make("Inside the Rubin platform memory design", source="SemiEngineering", sector="Semiconductors"),
            make("Lone unrelated gardening story today", source="Garden Weekly", sector="Space"),
        ]

    def test_detects_term_across_sources(self):
        found = {r["term"] for r in ins.emerging_terms(self.items(), {})}
        self.assertTrue(any("rubin" in t for t in found), found)
        self.assertFalse(any("gardening" in t for t in found))

    def test_requires_independent_sources(self):
        one_source = [make(f"Rubin platform story {n}", source="Same") for n in range(5)]
        self.assertEqual(ins.emerging_terms(one_source, {}), [])

    def test_staple_terms_in_baseline_are_not_emerging(self):
        baseline = {"rubin": 4.0, "rubin platform": 4.0, "platform": 4.0, "hyperscalers": 4.0, "hyperscalers order": 4.0}
        found = {r["term"] for r in ins.emerging_terms(self.items(), baseline)}
        self.assertNotIn("rubin", found)
        self.assertNotIn("rubin platform", found)

    def test_unigram_dropped_when_phrase_covers_it(self):
        terms = [r["term"] for r in ins.emerging_terms(self.items(), {})]
        if "rubin platform" in terms:
            self.assertNotIn("rubin", terms)

    def test_bigrams_do_not_span_dropped_stopwords(self):
        terms = ins.terms_in_item(make("Labs sign an MOU with regulators"))
        self.assertNotIn("sign mou", terms)
        self.assertIn("regulators", terms)

    def test_single_words_need_three_sources_but_phrases_need_two(self):
        two = [make("Rubin platform ships to customers", source="A"), make("Rubin platform memory design", source="B")]
        found = {r["term"] for r in ins.emerging_terms(two, {})}
        self.assertIn("rubin platform", found)
        self.assertNotIn("rubin", found)

    def test_baseline_builder_averages_per_day(self):
        snap = {"sectors": {"AI": [make("Rubin platform ships to hyperscalers")]}}
        baseline = ins.build_baseline([snap, {"sectors": {}}])
        self.assertAlmostEqual(baseline["rubin"], 0.5)
        self.assertEqual(ins.build_baseline([]), {})


class RecapAndStateTests(unittest.TestCase):
    def test_weekly_trigger(self):
        sunday, monday = NOW, NOW + timedelta(days=1)
        self.assertTrue(ins.should_generate_weekly(sunday, None))
        self.assertFalse(ins.should_generate_weekly(monday, None))
        self.assertFalse(ins.should_generate_weekly(sunday, {"week_ending": sunday.date().isoformat()}))
        self.assertTrue(ins.should_generate_weekly(sunday, {"week_ending": "2026-11-15"}))
        self.assertTrue(ins.should_generate_weekly(monday, None, force=True))

    def test_prune_state_drops_old_and_caps(self):
        fresh, old = make("Fresh item here today", hours_ago=2), make("Old item from last month", hours_ago=500)
        for i in (fresh, old):
            i["key"], i["last_seen"] = f"AI:{i['id']}", i["first_seen"]
        kept = ins.prune_state({fresh["key"]: fresh, old["key"]: old}, NOW)
        self.assertEqual(list(kept), [fresh["key"]])
        many = {}
        for n in range(10):
            it = make(f"Item {n} about something", hours_ago=n)
            it["key"], it["last_seen"] = f"AI:{it['id']}", it["first_seen"]
            many[it["key"]] = it
        self.assertEqual(len(ins.prune_state(many, NOW, max_items=3)), 3)

    def test_recap_lines_sorted_oldest_first(self):
        snaps = [
            {"date": "2026-11-21", "top_stories": [{"sector": "AI", "title": "B", "why_it_matters": "because"}]},
            {"date": "2026-11-20", "top_stories": [{"sector": "Space", "title": "A"}]},
        ]
        lines = ins.recap_lines(snaps)
        self.assertTrue(lines[0].startswith("2026-11-20"))
        self.assertIn("because", lines[1])

    def test_stale_hours(self):
        self.assertAlmostEqual(ins.stale_hours(iso(5), NOW), 5.0, places=3)
        self.assertEqual(ins.stale_hours(None, NOW), float("inf"))


class ModelOutputTests(unittest.TestCase):
    def test_parse_json_loose_handles_fences_and_prose(self):
        self.assertEqual(ins.parse_json_loose('```json\n[{"a": 1}]\n```'), [{"a": 1}])
        self.assertEqual(ins.parse_json_loose('Sure! Here you go: {"a": 2} Hope that helps'), {"a": 2})
        self.assertIsNone(ins.parse_json_loose("not json"))
        self.assertIsNone(ins.parse_json_loose(None))

    def test_parse_ai_batch_validates(self):
        reply = (
            '[{"id": "a1", "summary": "A concrete two sentence summary here.", "why_it_matters": "It matters.", "importance": 11},'
            ' {"id": "a2", "summary": "...", "importance": 5},'
            ' {"id": "zz", "summary": "Unknown id should be ignored entirely.", "importance": 5},'
            ' {"id": "a3", "summary": "<b>Bold</b> summary with markup inside it.", "importance": "high"}]'
        )
        out = ins.parse_ai_batch(reply, {"a1", "a2", "a3"})
        self.assertEqual(set(out), {"a1", "a3"})
        self.assertEqual(out["a1"]["importance"], 10.0)  # clamped
        self.assertIsNone(out["a3"]["importance"])
        self.assertNotIn("<b>", out["a3"]["summary"])

    def test_parse_ai_batch_accepts_wrapped_object_and_garbage(self):
        wrapped = '{"items": [{"id": "a1", "summary": "A valid summary sentence here.", "importance": 6}]}'
        self.assertIn("a1", ins.parse_ai_batch(wrapped, {"a1"}))
        self.assertEqual(ins.parse_ai_batch("oops", {"a1"}), {})
        self.assertEqual(ins.parse_ai_batch('"just a string"', {"a1"}), {})

    def test_validate_stocks(self):
        data = [
            {"ticker": "nvda", "company": "NVIDIA", "impact_blurb": "Could gain share."},
            {"ticker": "NOT A TICKER", "company": "Bad", "impact_blurb": "x"},
            {"ticker": "AMD", "company": "AMD", "impact_blurb": ""},
            {"ticker": "BRK.B", "company": "Berkshire", "impact_blurb": "Might benefit."},
            {"ticker": "TSM", "company": "TSMC", "impact_blurb": "Could benefit."},
            {"ticker": "INTC", "company": "Intel", "impact_blurb": "Could lose out."},
        ]
        out = ins.validate_stocks(data)
        self.assertEqual([s["ticker"] for s in out], ["NVDA", "BRK.B", "TSM"])
        self.assertEqual(ins.validate_stocks("nope"), [])


if __name__ == "__main__":
    unittest.main()
