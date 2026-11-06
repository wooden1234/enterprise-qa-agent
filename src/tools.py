"""文档检索和原文读取。检索不返回正文，避免把预览当成引用。"""

from __future__ import annotations

import re

from src.corpus import load_documents

_STOPWORDS = (
    "请问一下",
    "请问",
    "多少",
    "几天",
    "多久",
    "什么",
    "如何",
    "怎么",
    "是否",
    "可以",
    "我们",
    "咱们",
    "公司",
    "一共",
    "一下",
    "这个",
    "那个",
    "早上",
    "几点",
    "哪些",
    "额度",
    "的",
    "了",
    "是",
    "有",
    "在",
    "和",
    "与",
    "或",
    "及",
    "哪",
    "为",
    "吗",
    "呢",
)


def content_terms(query):
    """从问题里留下可能出现在制度正文中的连续词。"""
    text = re.sub(r"[？?！!。，、,.：:；;（）()\s]+", " ", str(query or ""))
    for word in sorted(_STOPWORDS, key=len, reverse=True):
        text = text.replace(word, " ")
    terms = []
    for part in text.split():
        while part.startswith(("那", "这")) and len(part) > 2:
            part = part[1:]
        if len(part) >= 2 and part not in terms:
            terms.append(part)
    return terms


def _score(document, terms):
    title = document["title"]
    body = document["text"]
    score = 0
    matched = []
    for term in terms:
        in_title = term in title
        in_body = term in body
        if in_title or in_body:
            score += len(term) + (5 if in_title else 0)
            matched.append(term)
    return score, matched


class Toolset:
    def __init__(self, documents=None, fail_tool=""):
        documents = documents if documents is not None else load_documents()
        self.documents = {item["doc_id"]: item for item in documents}
        self.fail_tool = fail_tool or ""

    def call(self, name, arguments):
        arguments = arguments if isinstance(arguments, dict) else {}
        if name == self.fail_tool:
            return {
                "ok": False,
                "tool": name,
                "arguments": arguments,
                "error": "simulated %s failure" % name,
            }
        if name == "search_documents":
            return self.search(str(arguments.get("query") or ""), arguments)
        if name == "read_document":
            return self.read(str(arguments.get("doc_id") or ""), arguments)
        return {
            "ok": False,
            "tool": name or "unknown",
            "arguments": arguments,
            "error": "未知工具，只能使用 search_documents 或 read_document",
        }

    def search(self, query, arguments=None):
        terms = content_terms(query)
        found = []
        for document in self.documents.values():
            score, matched = _score(document, terms)
            if score <= 0:
                continue
            found.append(
                {
                    "doc_id": document["doc_id"],
                    "title": document["title"],
                    "version_date": document["version_date"],
                    "score": score,
                    "matched_terms": matched,
                }
            )
        found.sort(key=lambda item: (-item["score"], item["doc_id"]))
        return {
            "ok": True,
            "tool": "search_documents",
            "arguments": arguments if arguments is not None else {"query": query},
            "query": query,
            "terms": terms,
            "match_count": len(found),
            "results": found[:5],
            "note": "结果不含正文。引用前必须 read_document。",
        }

    def read(self, doc_id, arguments=None):
        document = self.documents.get(doc_id)
        if document is None:
            return {
                "ok": False,
                "tool": "read_document",
                "arguments": arguments if arguments is not None else {"doc_id": doc_id},
                "error": "document_not_found",
                "doc_id": doc_id,
            }
        return {
            "ok": True,
            "tool": "read_document",
            "arguments": arguments if arguments is not None else {"doc_id": doc_id},
            "doc_id": document["doc_id"],
            "title": document["title"],
            "version_date": document["version_date"],
            "text": document["text"],
        }


def summarize(observation):
    if observation.get("type") == "review":
        return "提交未通过：" + str(observation.get("error") or "")
    if not observation.get("ok"):
        text = "失败：" + str(observation.get("error") or "未知错误")
        if observation.get("hint"):
            text += "；" + observation["hint"]
        return text
    tool_name = observation.get("tool")
    if tool_name == "search_documents":
        ids = [item["doc_id"] for item in observation.get("results") or []]
        if not ids:
            return "没有命中"
        return "命中 " + "、".join(ids)
    if tool_name == "read_document":
        return "已读取 %s，%d 字" % (observation.get("doc_id"), len(observation.get("text") or ""))
    if observation.get("type") == "review":
        return "提交未通过：" + str(observation.get("error") or "")
    return "已返回"
