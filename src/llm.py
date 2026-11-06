"""OpenAI 兼容聊天接口。模型只返回下一步 JSON，不在这里决定业务结论。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from src.corpus import load_rules

_ACTIONS = ("consult_retrieval", "search_documents", "read_document", "submit_answer", "submit_findings")


def system_prompt():
    return (
        "你是企业知识问答的主助手，负责判断问题和总结答案。每一步只输出一个 JSON 对象，不要使用 Markdown。\n"
        "JSON 字段：decision_basis（不超过 40 字）、action、arguments。\n"
        "action 只能是 consult_retrieval 或 submit_answer。\n"
        "问候、感谢、告别和其他闲聊直接 submit_answer，不要调用检索。"
        "这时 answer_kind 是 chat，status 是 completed，citations 是空数组。\n"
        "制度、流程、假期、报销、设备等问题调用 consult_retrieval，arguments 是 {\"query\": \"要查的问题\"}。\n"
        "不要自己搜索或阅读原文。检索子代理会自己检索和阅读，然后只交回一种状态："
        "ready、needs_confirmation、insufficient_evidence、tool_error。\n"
        "status 为 tool_error 时，用相同 query 再调用一次 consult_retrieval。"
        "第二次仍失败再 submit_answer，status 用 tool_error，不要编造答案。\n"
        "ready 时作答，answer_kind 是 policy，status 是 completed。\n"
        "needs_confirmation 时并列引用两边原文，不要选定其中一个版本。\n"
        "citations 必须是对象数组，不能写成字符串数组。"
        "每一项形如 {\"doc_id\":\"D03\",\"quote\":\"已读原文中的连续片段\"}，quote 必须来自 findings。\n"
        "insufficient_evidence 时说明没有依据，citations 为空。\n"
        "submit_answer 的 arguments 是 "
        "{\"status\",\"answer\",\"citations\",\"gaps\",\"confirmation_needed\",\"answer_kind\"}。\n"
        "status 只能是 completed、needs_confirmation、insufficient_evidence、tool_error。\n"
        "提交会经过审核。工具结果以“提交未通过”开头时，按审核意见修改后重新 submit_answer。\n"
        "没有确认事项时 confirmation_needed 用空字符串。gaps 没有内容时用空数组。\n\n"
        "制度规则：\n"
        + load_rules()
    )


def retrieval_system_prompt():
    return (
        "你是制度检索子代理。每一步只输出一个 JSON 对象，不要使用 Markdown。\n"
        "JSON 字段：decision_basis（不超过 40 字）、action、arguments。\n"
        "action 只能是 search_documents、read_document、submit_findings。\n"
        "第一次 search_documents 的 query 必须是用户原句，不要提前改写。\n"
        "search_documents 的 arguments 是 {\"query\": \"检索词\"}。"
        "只有上一则结果是没有命中时，才换一个更接近制度原文的检索词再查，例如年假。\n"
        "read_document 的 arguments 是 {\"section_id\": \"检索结果里的 section_id\"}。"
        "同一事项的多个版本文档都要读。\n"
        "工具失败时不要用相同参数重试，直接 submit_findings，status 为 tool_error，findings 为空。\n"
        "submit_findings 的 arguments 是 {\"status\",\"findings\",\"gaps\",\"confirmation_needed\"}。\n"
        "status 只能是 ready、needs_confirmation、insufficient_evidence、tool_error。\n"
        "findings 的每一项是 {\"doc_id\",\"section_id\",\"quote\"}，quote 必须是已读原文的连续片段。\n"
        "两个版本对同一事实不一致且没有优先级时，status 用 needs_confirmation，两边都放进 findings。\n"
        "没有资料时 status 用 insufficient_evidence。不要写给用户的最终回答。\n"
    )


def parse_action(text):
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError("模型输出不是 JSON")
    try:
        payload, _end = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise ValueError("模型输出不是 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("模型输出不是 JSON 对象")
    action = str(payload.get("action") or "")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    basis = str(payload.get("decision_basis") or "").strip() or "模型未提供决策依据"
    if action not in _ACTIONS:
        raise ValueError("未知动作：" + action)
    return {"action": action, "arguments": arguments, "decision_basis": basis[:80]}


class ModelError(RuntimeError):
    pass


class OpenAICompatibleModel:
    mode = "live_model"

    def __init__(self, base_url, api_key, model):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    @classmethod
    def from_env(cls):
        from src.retrieval.settings import load_env_file

        load_env_file()
        base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or ""
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("DEEPSEEK_MODEL") or ""
        if not base_url or not api_key or not model:
            raise ModelError(
                "缺少 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL，"
                "或对应的 DEEPSEEK_BASE_URL / DEEPSEEK_API_KEY / DEEPSEEK_MODEL"
            )
        return cls(base_url, api_key, model)

    def complete(self, messages):
        url = self.base_url + "/chat/completions"
        body = {
            "model": self.model_name,
            "temperature": 0,
            "messages": messages,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ModelError("模型请求失败：HTTP %s %s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise ModelError("模型请求失败：%s" % exc.reason) from exc
        usage = payload.get("usage") or {}
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        message = ((payload.get("choices") or [{}])[0].get("message") or {})
        content = message.get("content") or ""
        try:
            action = parse_action(content)
        except ValueError as exc:
            action = {
                "action": "invalid",
                "arguments": {},
                "decision_basis": str(exc)[:80],
            }
            content = json.dumps(action, ensure_ascii=False)
        return content, action
