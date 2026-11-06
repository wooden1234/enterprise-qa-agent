import json
import unittest

from src.agent import run
from src.harness.control.policy import review_submission, version_conflict
from src.harness.knowledge.index import SectionIndex
from src.scripted import ScriptedModel


class QueueModel:
    mode = "queue"
    model_name = "queue"

    def __init__(self, actions):
        self.actions = list(actions)
        self.seen = []

    def complete(self, messages):
        self.seen.append(messages)
        action = self.actions.pop(0)
        return json.dumps(action, ensure_ascii=False), action


def _submit(status, answer, citations, confirmation=""):
    return {
        "decision_basis": "根据已读原文提交",
        "action": "submit_answer",
        "arguments": {
            "status": status,
            "answer": answer,
            "citations": citations,
            "gaps": [],
            "confirmation_needed": confirmation,
        },
    }


def _annual_sections():
    index = SectionIndex.load()
    found = []
    for item in index.search("年假")["results"]:
        if "八、年假" in item["heading"]:
            found.append(index.read(item["section_id"]))
    return found


class LoopTests(unittest.TestCase):
    def test_events_follow_the_harness_step_order(self):
        result = run({"question": "公司班车早上几点发车？", "max_steps": 3})
        types = [item["event_type"] for item in result["events"]]
        self.assertEqual(types[0], "turn/start")
        self.assertIn("step/start", types)
        self.assertIn("assistant/message", types)
        self.assertIn("tool/result", types)
        self.assertEqual(types[-1], "turn/end")
        self.assertEqual(result["finish_reason"], "completed")
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_version_conflict_changes_the_final_status(self):
        sections = _annual_sections()
        self.assertEqual(len(sections), 2)
        model = QueueModel(
            [
                {
                    "decision_basis": "交给检索子代理",
                    "action": "consult_retrieval",
                    "arguments": {"query": "年假"},
                },
                _submit(
                    "needs_confirmation",
                    "两版年假天数不同，请确认。",
                    [
                        {"doc_id": sections[0]["doc_id"], "quote": "年休假 5 个工作日"},
                        {"doc_id": sections[1]["doc_id"], "quote": "年休假 10 个工作日"},
                    ],
                    "请确认适用哪一版。",
                ),
            ]
        )
        result = run({"question": "年假有多少天？"}, model)
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual({item["doc_id"] for item in result["citations"]}, {"D03", "D04"})
        self.assertEqual(result["events"][-1]["event_type"], "turn/end")
        self.assertEqual(result["events"][-1]["data"]["reason"], "completed")

    def test_rejected_answer_is_returned_as_tool_result(self):
        model = QueueModel(
            [
                {"decision_basis": "交给检索子代理", "action": "consult_retrieval", "arguments": {"query": "年假"}},
                _submit("completed", "年假是 5 个工作日。", [{"doc_id": "D03", "quote": "年休假 5 个工作日"}]),
                _submit(
                    "needs_confirmation",
                    "D03 写 5 个工作日，D04 写 10 个工作日，请确认。",
                    [
                        {"doc_id": "D03", "quote": "年休假 5 个工作日"},
                        {"doc_id": "D04", "quote": "年休假 10 个工作日"},
                    ],
                    "请确认适用哪一版。",
                ),
            ]
        )
        result = run({"question": "年假有多少天？"}, model)
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertTrue(any(item["event_type"] == "tool/result" and "不要选定其中一个" in item["data"]["summary"] for item in result["events"]))

    def test_step_limit_returns_incomplete(self):
        model = QueueModel(
            [
                {"decision_basis": "检索", "action": "search_documents", "arguments": {"query": "年假"}},
                {"decision_basis": "继续检索", "action": "search_documents", "arguments": {"query": "年休假"}},
            ]
        )
        result = run({"question": "年假有多少天？", "max_steps": 1}, model)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["finish_reason"], "incomplete")
        self.assertIn("未完成", result["gaps"][0])
        self.assertEqual(result["trace"][-1]["next_action"], "incomplete")
        self.assertEqual(len(model.actions), 1)

    def test_conflict_detector_uses_read_sections(self):
        sections = {item["section_id"]: item for item in _annual_sections()}
        self.assertTrue(version_conflict(sections))
        blocked = review_submission(
            {
                "status": "completed",
                "answer": "5 个工作日",
                "citations": [{"doc_id": "D03", "quote": "年休假 5 个工作日"}],
                "gaps": [],
                "confirmation_needed": "",
            },
            sections,
        )
        self.assertIn("needs_confirmation", blocked)

    def test_string_citation_tells_the_model_the_object_shape(self):
        blocked = review_submission(
            {
                "status": "needs_confirmation",
                "answer": "两版不一致",
                "citations": ["年休假 5 个工作日"],
                "gaps": [],
                "confirmation_needed": "请确认适用哪一版。",
            },
            {},
        )
        self.assertIn("doc_id", blocked)
        self.assertIn("quote", blocked)


class ScriptedFlowTests(unittest.TestCase):
    def run_case(self, request):
        return run(request, ScriptedModel())

    def test_annual_leave_asks_which_version(self):
        result = self.run_case({"question": "年假有多少天？"})
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["mode"], "scripted_mock")
        self.assertEqual({item["doc_id"] for item in result["citations"]}, {"D03", "D04"})
        self.assertIn("5 个工作日", result["answer"])
        self.assertIn("10 个工作日", result["answer"])
        self.assertIn("确认", result["answer"])

    def test_paraphrase_rewrites_then_sees_conflict(self):
        result = self.run_case({"question": "员工每年的带薪休假额度是几天？"})
        retrieval = _retrieval_trace(result)
        self.assertEqual(result["trace"][0]["action"], "consult_retrieval")
        self.assertEqual(retrieval[0]["observation_summary"], "没有命中")
        self.assertEqual(retrieval[1]["arguments"]["query"], "年假")
        self.assertEqual(result["status"], "needs_confirmation")

    def test_followup_reads_sick_leave(self):
        result = self.run_case(
            {
                "question": "那病假呢？",
                "history": [
                    {"role": "user", "content": "年假有多少天？"},
                    {"role": "assistant", "content": "两版年假不一致，需要确认。"},
                ],
            }
        )
        self.assertIn("病假", result["trace"][0]["arguments"]["query"])
        self.assertEqual(result["trace"][0]["action"], "consult_retrieval")
        self.assertEqual(result["status"], "completed")
        self.assertIn("区级以上医院", result["citations"][0]["quote"])

    def test_insufficient_evidence(self):
        result = self.run_case({"question": "公司班车早上几点发车？"})
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["citations"], [])
        retrieval = _retrieval_trace(result)
        self.assertGreaterEqual(sum(item["observation_summary"] == "没有命中" for item in retrieval), 2)

    def test_tool_failure(self):
        result = self.run_case({"question": "年假有多少天？", "simulate_tool_failure": "search_documents"})
        self.assertEqual(result["status"], "tool_error")
        self.assertEqual(result["citations"], [])
        self.assertNotIn("5 个工作日", result["answer"])
        consults = [item for item in result["trace"] if item["action"] == "consult_retrieval"]
        self.assertEqual(len(consults), 2)
        self.assertEqual(consults[1]["arguments"]["query"], consults[0]["arguments"]["query"])
        for event in result["events"]:
            observation = (event.get("data") or {}).get("observation") or {}
            if observation.get("tool") != "consult_retrieval":
                continue
            searches = [item for item in observation.get("retrieval_trace") or [] if item["action"] == "search_documents"]
            self.assertEqual(len(searches), 1)
            self.assertEqual(observation["status"], "tool_error")

    def test_step_limit(self):
        result = self.run_case({"question": "年假有多少天？", "max_steps": 1})
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("未完成", result["gaps"][0])

    def test_greeting_is_answered_without_retrieval(self):
        result = self.run_case({"question": "你好"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["trace"][0]["action"], "submit_answer")
        self.assertIn("你好", result["answer"])
        self.assertNotIn("consult_retrieval", [item["action"] for item in result["trace"]])


def _retrieval_trace(result):
    for event in result["events"]:
        if event["event_type"] != "tool/result":
            continue
        observation = event["data"].get("observation") or {}
        if observation.get("tool") == "consult_retrieval":
            return observation.get("retrieval_trace") or []
    return []


if __name__ == "__main__":
    unittest.main()
