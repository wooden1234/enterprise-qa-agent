import json
import unittest
from pathlib import Path

from unittest.mock import patch

from src.agent import run
from src.corpus import load_documents
from src.harness.knowledge.index import SectionIndex
from src.scripted import ScriptedModel

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DOCS = {item["doc_id"]: item for item in load_documents()}


def load_dataset():
    return json.loads((EXAMPLES / "dataset.json").read_text(encoding="utf-8"))


def retrieval_trace(result):
    for event in result["events"]:
        observation = (event.get("data") or {}).get("observation") or {}
        if observation.get("tool") == "consult_retrieval":
            return observation.get("retrieval_trace") or []
    return []


class OfflineDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_dataset()["cases"]

    def test_inputs_match_the_dataset(self):
        ids = [item["id"] for item in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for case in self.cases:
            path = EXAMPLES / ("%s.input.json" % case["id"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), case["request"])

    def test_scripted_replay_matches_each_label(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = run(case["request"], ScriptedModel())
                self._check(case["expect"], result)

    def _check(self, expect, result):
        self.assertEqual(result["status"], expect["status"])
        self.assertEqual(result["mode"], "scripted_mock")
        answer = result["answer"]
        for text in expect.get("answer_contains") or []:
            self.assertIn(text, answer)
        for text in expect.get("answer_excludes") or []:
            self.assertNotIn(text, answer)
        citations = result["citations"]
        self.assertEqual(sorted(item["doc_id"] for item in citations), sorted(expect["citation_doc_ids"]))
        self.assertTrue(_quotes_match_source(citations))
        for text in expect.get("quote_contains") or []:
            self.assertTrue(any(text in item["quote"] for item in citations))
        if expect.get("confirmation"):
            self.assertTrue(result["confirmation_needed"])
        if expect.get("gaps"):
            self.assertTrue(result["gaps"])
        if expect.get("gap_contains"):
            self.assertTrue(any(expect["gap_contains"] in item for item in result["gaps"]))
        actions = [item["action"] for item in result["trace"]]
        if "trace_actions" in expect:
            self.assertEqual(actions, expect["trace_actions"])
        if expect.get("trace_query_contains"):
            self.assertIn(expect["trace_query_contains"], result["trace"][0]["arguments"]["query"])
        if expect.get("consult_count") is not None:
            self.assertEqual(actions.count("consult_retrieval"), expect["consult_count"])
        if expect.get("next_action"):
            self.assertEqual(result["trace"][-1]["next_action"], expect["next_action"])
        if expect.get("answer_kind"):
            self.assertEqual(result["trace"][-1]["arguments"]["answer_kind"], expect["answer_kind"])
        retrieval = retrieval_trace(result)
        if expect.get("retrieval_misses") is not None:
            misses = sum(item["observation_summary"] == "没有命中" for item in retrieval)
            self.assertGreaterEqual(misses, expect["retrieval_misses"])
        if expect.get("retrieval_first_summary"):
            self.assertEqual(retrieval[0]["observation_summary"], expect["retrieval_first_summary"])
        if expect.get("retrieval_later_query"):
            later = [item["arguments"].get("query") for item in retrieval[1:]]
            self.assertIn(expect["retrieval_later_query"], later)


class ContentSwapTests(unittest.TestCase):
    def test_replacing_the_device_cycle_changes_the_quote(self):
        original = SectionIndex.read

        def patched(self, section_id, arguments=None):
            result = original(self, section_id, arguments)
            if result.get("ok") and result.get("text"):
                result = dict(result)
                result["text"] = result["text"].replace("36 个月", "24 个月")
            return result

        with patch.object(SectionIndex, "read", patched):
            result = run({"question": "笔记本电脑的更换周期是多久？"}, ScriptedModel())
        self.assertEqual(result["status"], "completed")
        self.assertIn("24", result["citations"][0]["quote"])
        self.assertNotIn("36", result["citations"][0]["quote"])
        self.assertNotIn("36", result["answer"])
        retrieval = retrieval_trace(result)
        self.assertEqual([item["action"] for item in retrieval[:2]], ["search_documents", "read_document"])


def _quotes_match_source(citations):
    for citation in citations:
        source = DOCS[citation["doc_id"]]
        compact_quote = "".join(citation["quote"].split())
        compact_text = "".join(source["text"].split())
        if compact_quote not in compact_text:
            return False
        if citation["version_date"] != source["version_date"]:
            return False
    return True


if __name__ == "__main__":
    unittest.main()
