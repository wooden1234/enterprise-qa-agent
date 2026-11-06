import unittest
from unittest.mock import patch

from src.agent import run
from src.harness.session.surface import messages_for_llm
from src.llm import system_prompt
from src.memory.preferences import compose_system, preference_block
from src.memory.store import load_preferences


class _CaptureModel:
    mode = "queue"
    model_name = "queue"

    def __init__(self):
        self.seen = []

    def complete(self, messages):
        self.seen.append(messages)
        action = {
            "decision_basis": "闲聊直接回答",
            "action": "submit_answer",
            "arguments": {
                "status": "completed",
                "answer": "你好。",
                "citations": [],
                "gaps": [],
                "confirmation_needed": "",
                "answer_kind": "chat",
            },
        }
        return "{}", action


class PreferencePromptTests(unittest.TestCase):
    def test_block_lists_saved_preferences(self):
        text = preference_block({"response_language": "en-US", "unknown": "x", "citation_preference": None})
        self.assertIn("- response_language=en-US", text)
        self.assertNotIn("unknown", text)
        self.assertEqual(preference_block({}), "")

    def test_compose_keeps_the_stable_prompt_first(self):
        text = compose_system(system_prompt(), {"response_detail_level": "brief"})
        self.assertTrue(text.startswith("你是企业知识问答"))
        self.assertIn("[用户长期偏好]", text)
        self.assertIn("response_detail_level=brief", text)

    def test_prompt_omits_finding_text(self):
        event = type("Event", (), {})()
        event.event_type = "tool/result"
        event.data = {
            "observation": {
                "tool": "consult_retrieval",
                "findings": [{"doc_id": "D03", "quote": "年休假 5 个工作日。", "text": "整段原文不应进入提示词"}],
            }
        }
        messages = messages_for_llm([event])
        self.assertIn("年休假 5 个工作日。", messages[0]["content"])
        self.assertNotIn("整段原文不应进入提示词", messages[0]["content"])

    def test_every_assembly_appends_preferences(self):
        messages = messages_for_llm([], system=system_prompt(), preferences={"citation_preference": "always"})
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("citation_preference=always", messages[0]["content"])
        plain = messages_for_llm([], system=system_prompt(), preferences={})
        self.assertNotIn("用户长期偏好", plain[0]["content"])

    def test_missing_database_returns_no_preferences(self):
        with patch("src.retrieval.pgstore.connect", return_value=None):
            self.assertEqual(load_preferences("default"), {})

    def test_loop_reloads_preferences_into_the_model_prompt(self):
        model = _CaptureModel()
        with patch("src.memory.store.load_preferences", return_value={"response_language": "en-US"}) as loaded:
            result = run({"question": "你好", "user_id": "u1"}, model)
        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(loaded.call_count, 2)
        self.assertEqual(loaded.call_args[0][0], "u1")
        self.assertIn("response_language=en-US", model.seen[0][0]["content"])
        self.assertIn("[用户长期偏好]", result["events"][0]["data"].get("system", "") or _header_system(result))


def _header_system(result):
    for event in result["events"]:
        if event["event_type"] == "request/header":
            return event["data"]["system"]
    return ""
