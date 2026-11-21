"""Tests for the Claude wrapper and AI-attempt accounting (fake client, no network)."""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_data as fd  # noqa: E402


class ApiError(Exception):
    def __init__(self, status, message="boom"):
        super().__init__(message)
        self.status_code = status


def reply(text, stop_reason="end_turn"):
    block = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(content=[block, types.SimpleNamespace(type="thinking", text="ignored")], stop_reason=stop_reason)


class FakeClient:
    """Minimal stand-in for anthropic.Anthropic: messages.create returns or raises from a script."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        step = self.script.pop(0) if self.script else reply("[]")
        if isinstance(step, Exception):
            raise step
        return step


class WrapperTests(unittest.TestCase):
    def test_success_sends_system_and_user_separately(self):
        client = FakeClient([reply("[1]")])
        with mock.patch.dict(os.environ, {"CLAUDE_MODEL": ""}):
            llm = fd.LLM(client=client)
        self.assertEqual(llm.generate_json("SYS", "USER", max_tokens=99), "[1]")  # non-text blocks ignored
        sent = client.requests[0]
        self.assertEqual((sent["system"], sent["max_tokens"], sent["model"]), ("SYS", 99, "claude-haiku-5-5"))
        self.assertEqual(sent["messages"], [{"role": "user", "content": "USER"}])
        self.assertEqual(llm.calls, 1)

    def test_model_can_be_overridden(self):
        with mock.patch.dict(os.environ, {"CLAUDE_MODEL": "claude-sonnet-5-5"}):
            self.assertEqual(fd.LLM(client=FakeClient([])).model, "claude-sonnet-5-5")

    def test_missing_key_and_no_ai_flag(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            llm = fd.LLM()
        self.assertFalse(llm.available)
        self.assertIn("ANTHROPIC_API_KEY is not set", llm.errors[0])
        self.assertIsNone(llm.generate_json("s", "u"))
        self.assertIn("--no-ai", fd.LLM(enabled=False).errors[0])

    def test_fatal_status_switches_ai_off_after_one_call(self):
        for status in (401, 403, 404):
            client = FakeClient([ApiError(status, "model not found")])
            llm = fd.LLM(client=client)
            self.assertIsNone(llm.generate_json("s", "u"))
            self.assertFalse(llm.available)
            self.assertIsNone(llm.generate_json("s", "u"))
            self.assertEqual(len(client.requests), 1, status)
            self.assertTrue(any("switched off" in e for e in llm.errors))

    def test_transient_errors_do_not_disable_until_three_in_a_row(self):
        client = FakeClient([ApiError(529), ApiError(529), reply("ok"), ApiError(529), ApiError(529), ApiError(529)])
        llm = fd.LLM(client=client)
        results = [llm.generate_json("s", "u") for _ in range(6)]
        self.assertEqual(results[:3], [None, None, "ok"])  # success resets the streak
        self.assertFalse(llm.available)
        self.assertIsNone(llm.generate_json("s", "u"))
        self.assertEqual(len(client.requests), 6)

    def test_truncated_reply_is_noted(self):
        llm = fd.LLM(client=FakeClient([reply("[", stop_reason="max_tokens")]))
        llm.generate_json("s", "u")
        self.assertTrue(any("cut off" in e for e in llm.errors))


def make_items(count, sectors=("AI", "Space")):
    items = {}
    for n in range(count):
        sector = sectors[n % len(sectors)]
        items[f"{sector}:{n}"] = {
            "id": f"id{n}", "key": f"{sector}:{n}", "title": f"Title {n}", "source": "S", "type": "news",
            "sector": sector, "text": "A long enough description of the story to summarise properly.",
            "summary": "", "summary_source": None, "ai_attempts": 0, "importance": None, "why_it_matters": "",
        }
    return items


def answer_all(user):
    rows = json.loads(user.split("ITEMS:\n", 1)[1])
    return json.dumps([{"id": r["id"], "summary": f"Summary for {r['id']} with some detail.", "why_it_matters": "Because.", "importance": 6} for r in rows])


class AttemptAccountingTests(unittest.TestCase):
    def test_fatal_error_stops_after_first_batch_and_does_not_burn_attempts(self):
        items = make_items(45)  # 4+ batches across two sectors
        client = FakeClient([ApiError(404, "no such model")])
        llm = fd.LLM(client=client)
        self.assertEqual(fd.enrich_items(llm, items), 0)
        self.assertEqual(len(client.requests), 1)  # fail fast, not one failing call per batch
        self.assertTrue(all(i["ai_attempts"] == 0 for i in items.values()))  # an outage is not the item's fault
        self.assertTrue(all(i["summary_source"] in ("feed", "none") for i in items.values()))

    def test_answered_but_omitted_items_count_as_an_attempt(self):
        items = make_items(3, sectors=("AI",))

        class Partial(FakeClient):
            def _create(self, **kw):
                rows = json.loads(kw["messages"][0]["content"].split("ITEMS:\n", 1)[1])
                body = json.loads(answer_all(kw["messages"][0]["content"]))[:1]  # model forgot two items
                return reply(json.dumps(body))

        client = Partial([])
        client.messages = types.SimpleNamespace(create=client._create)
        llm = fd.LLM(client=client)
        self.assertEqual(fd.enrich_items(llm, items), 1)
        self.assertEqual(sorted(i["ai_attempts"] for i in items.values()), [1, 1, 1])
        self.assertEqual(sorted(i["summary_source"] for i in items.values()), ["ai", "feed", "feed"])

    def test_items_stop_retrying_after_max_attempts(self):
        items = make_items(1, sectors=("AI",))
        item = next(iter(items.values()))
        item["ai_attempts"] = fd.MAX_AI_ATTEMPTS
        client = FakeClient([])
        fd.enrich_items(fd.LLM(client=client), items)
        self.assertEqual(client.requests, [])


if __name__ == "__main__":
    unittest.main()
