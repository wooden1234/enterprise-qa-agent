"""提交检查。只拒绝站不住的结论，不代替模型选择状态。"""

from __future__ import annotations

import re

_STATUSES = ("completed", "needs_confirmation", "insufficient_evidence", "tool_error")
_ANNUAL = re.compile(r"不满 10 年的，年休假 (\d+) 个工作日")
_REIMBURSE = re.compile(r"报销期限为 (\d+) 天")


def _norm(text):
    return "".join(str(text or "").split())


def version_conflict(reads):
    """已读片段对同一档年假或报销期限给出不同天数，或对是否当年休完规定不同。"""
    numbers = set()
    deadlines = set()
    claim_days = set()
    for item in reads.values():
        text = item.get("text") or ""
        numbers.update(_ANNUAL.findall(text))
        if "年休假必须于当年休完" in text:
            deadlines.add("same_year")
        if "顺延至次年" in text:
            deadlines.add("carry")
        if "优先适用" in text or "仅适用" in text:
            continue
        claim_days.update(_REIMBURSE.findall(text))
    if len(numbers) >= 2 or len(deadlines) >= 2 or len(claim_days) >= 2:
        return True
    return False


def review_submission(arguments, reads):
    if not isinstance(arguments, dict):
        return "arguments 必须是对象"
    status = arguments.get("status")
    if status not in _STATUSES:
        return "status 必须是 completed、needs_confirmation、insufficient_evidence 或 tool_error"
    citations = arguments.get("citations") if arguments.get("citations") is not None else []
    gaps = arguments.get("gaps") if arguments.get("gaps") is not None else []
    if not isinstance(citations, list) or not isinstance(gaps, list):
        return "citations 和 gaps 必须是数组"
    confirmation = arguments.get("confirmation_needed")
    if confirmation is None:
        confirmation = ""
    if not isinstance(confirmation, str):
        return "confirmation_needed 必须是字符串"
    if status in ("insufficient_evidence", "tool_error") and citations:
        return "资料不足或工具失败时不要附带引用"
    if status == "needs_confirmation" and not confirmation.strip():
        return "needs_confirmation 必须写明要用户确认的问题"
    checked = []
    for item in citations:
        if not isinstance(item, dict):
            return "引用必须是对象，每一项形如 {\"doc_id\":\"D03\",\"quote\":\"原文片段\"}，不能只写字符串"
        doc_id = str(item.get("doc_id") or "")
        quote = str(item.get("quote") or "")
        source = _source_for(reads, doc_id, quote)
        if source is None:
            return "引用 %s 之前没有读取对应原文" % (doc_id or "空编号")
        checked.append(source)
    if status == "completed" and arguments.get("answer_kind") == "chat":
        if checked:
            return "闲聊回答不要附带制度引用"
        return None
    if status == "completed":
        if not checked:
            return "completed 至少要有一条原文引用"
        if version_conflict(reads):
            return (
                "已读原文对同一档年假、休完期限或报销期限不一致，且没有版本优先级。"
                "请改用 needs_confirmation，并列引用，不要选定其中一个"
            )
    if status == "needs_confirmation" and len(checked) < 2:
        return "needs_confirmation 至少并列引用两段原文"
    return None


def enrich_citations(arguments, reads):
    citations = []
    for item in arguments.get("citations") or []:
        source = _source_for(reads, item["doc_id"], item["quote"])
        citations.append(
            {
                "doc_id": source["doc_id"],
                "title": source["title"],
                "version_date": source["version_date"],
                "heading": source.get("heading") or "",
                "section_id": source.get("section_id") or "",
                "quote": item["quote"],
            }
        )
    return citations


def _source_for(reads, doc_id, quote):
    compact = _norm(quote)
    if len(compact) < 4:
        return None
    for item in reads.values():
        if item.get("doc_id") != doc_id:
            continue
        if compact in _norm(item.get("text") or ""):
            return item
    return None
