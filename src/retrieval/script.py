"""检索子代理的离线策略。只在 scripted_mock 中使用，不证明模型会改下一步。"""

from __future__ import annotations

import json

from src.tools import content_terms


class RetrievalScript:
    mode = "retrieval_script"
    model_name = "retrieval-script"

    def __init__(self):
        self.question = ""
        self.reads = {}
        self.hits = []
        self.empty_searches = 0
        self.last_search = None

    def complete(self, messages):
        self.question = _question(messages) or self.question
        action = self._decide(_last_observation(messages))
        return json.dumps(action, ensure_ascii=False), action

    def _decide(self, observation):
        if observation and observation.get("ok") is False and observation.get("tool") in (
            "search_documents",
            "read_document",
        ):
            return _action(
                "工具失败，不再重试，把失败状态交回主代理",
                "submit_findings",
                {
                    "status": "tool_error",
                    "findings": [],
                    "gaps": [observation.get("error") or "工具失败"],
                    "confirmation_needed": "",
                },
            )
        if observation and observation.get("ok") and observation.get("tool") == "search_documents":
            self.hits = _select_sections(
                observation.get("results") or [],
                self.question + " " + str((self.last_search or {}).get("query") or ""),
            )
            if not self.hits:
                self.empty_searches += 1
                rewritten = self._rewrite() if self.empty_searches == 1 else ""
                if rewritten and rewritten != (self.last_search or {}).get("query"):
                    self.last_search = {"query": rewritten}
                    return _action("原词没有命中，改写检索词再查", "search_documents", self.last_search)
                return _action(
                    "改写后仍然没有资料",
                    "submit_findings",
                    {
                        "status": "insufficient_evidence",
                        "findings": [],
                        "gaps": ["没有命中相关制度"],
                        "confirmation_needed": "",
                    },
                )
            unread = [item for item in self.hits if item["section_id"] not in self.reads]
            if unread:
                return _action("检索命中后读取章节原文", "read_document", {"section_id": unread[0]["section_id"]})
            return self._finish()
        if observation and observation.get("ok") and observation.get("tool") == "read_document":
            self.reads[observation["section_id"]] = observation
            unread = [item for item in self.hits if item["section_id"] not in self.reads]
            if unread:
                return _action("同一检索里还有未读章节，继续读取", "read_document", {"section_id": unread[0]["section_id"]})
            return self._finish()
        query = " ".join(content_terms(self.question)) or self.question
        self.last_search = {"query": query}
        return _action("先用问题中的原词检索", "search_documents", self.last_search)

    def _rewrite(self):
        if "休假" in self.question or "带薪假" in self.question or "pto" in self.question.lower() or "歇班券" in self.question:
            return "年假"
        if "班车" in self.question:
            return "班车时刻"
        return ""

    def _finish(self):
        findings = []
        annual = []
        claims = []
        for item in self.reads.values():
            annual_line = _line_with(item.get("text") or "", "不满 10 年的，年休假")
            claim_line = _line_with(item.get("text") or "", "报销期限为")
            quote = annual_line or claim_line or _fact_quote(item.get("text") or "")
            findings.append(_finding(item, quote))
            if annual_line:
                annual.append(annual_line)
            if claim_line:
                claims.append(claim_line)
        if len(set(claims)) >= 2:
            return _action(
                "两个版本的报销期限不同，交回主代理确认",
                "submit_findings",
                {
                    "status": "needs_confirmation",
                    "findings": findings,
                    "gaps": ["缺少版本优先级"],
                    "confirmation_needed": "请确认应适用哪一条报销期限。",
                },
            )
        if len(set(annual)) >= 2:
            return _action(
                "两个版本的年假天数不同，交回主代理确认",
                "submit_findings",
                {
                    "status": "needs_confirmation",
                    "findings": findings,
                    "gaps": ["缺少版本优先级"],
                    "confirmation_needed": "请确认应适用哪一版假期管理制度。",
                },
            )
        if findings:
            return _action(
                "已读到原文，交回主代理总结",
                "submit_findings",
                {"status": "ready", "findings": findings, "gaps": [], "confirmation_needed": ""},
            )
        return _action(
            "没有可读原文",
            "submit_findings",
            {
                "status": "insufficient_evidence",
                "findings": [],
                "gaps": ["没有读取到文档"],
                "confirmation_needed": "",
            },
        )


def _question(messages):
    for message in reversed(messages):
        content = str(message.get("content") or "")
        if message.get("role") == "user" and content.startswith("当前问题："):
            return content.split("：", 1)[1]
    return ""


def _last_observation(messages):
    if not messages:
        return None
    content = str(messages[-1].get("content") or "")
    if messages[-1].get("role") != "user" or not content.startswith("工具结果："):
        return None
    return json.loads(content.split("\n", 1)[1])


_FACT_MARKERS = (
    "不满 10 年的，年休假",
    "必须提供区级以上医院的诊断证明或住院证明",
    "设备更换周期为 36 个月。",
)


def _select_sections(results, question):
    if "病假" in question:
        key = "病假"
    elif "年假" in question or "休假" in question:
        key = "年假"
    elif "期限" in question:
        key = "报销期限"
    elif "报销" in question:
        key = "报销时间"
    elif "笔记本" in question or "设备" in question:
        key = "更换周期"
    else:
        key = ""
    if key:
        chosen = [item for item in results if key in item.get("heading", "")]
        if chosen:
            return chosen
    return results[:1]


def _line_with(text, marker):
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("-").strip()
        if marker in line:
            return line
    return ""


def _fact_quote(text):
    for marker in _FACT_MARKERS:
        sentence = _line_with(text, marker)
        if sentence:
            return sentence
    compact = "".join(str(text or "").split())
    return compact[:80] if compact else text


def _finding(item, quote):
    return {
        "doc_id": item.get("doc_id"),
        "title": item.get("title"),
        "version_date": item.get("version_date"),
        "heading": item.get("heading"),
        "section_id": item.get("section_id"),
        "quote": quote,
        "text": item.get("text") or "",
    }


def _action(basis, name, arguments):
    return {"decision_basis": basis, "action": name, "arguments": arguments}
