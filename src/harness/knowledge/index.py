"""按章节和条款把制度切成可检索片段。"""

from __future__ import annotations

import re

from src.corpus import load_documents
from src.tools import content_terms

_ARTICLE = re.compile(r"^第[0-9０-９一二三四五六七八九十百零]+条")


class SectionIndex:
    def __init__(self, sections):
        self.sections = list(sections)
        self.by_id = {item["section_id"]: item for item in self.sections}

    @classmethod
    def load(cls, documents=None):
        documents = documents if documents is not None else load_documents()
        sections = []
        for document in documents:
            sections.extend(_split_document(document))
        return cls(sections)

    def search(self, query, arguments=None):
        terms = content_terms(query)
        found = []
        for section in self.sections:
            score, matched = _score(section, terms)
            if score <= 0:
                continue
            found.append(
                {
                    "section_id": section["section_id"],
                    "doc_id": section["doc_id"],
                    "title": section["title"],
                    "version_date": section["version_date"],
                    "heading": section["heading"],
                    "score": score,
                    "matched_terms": matched,
                }
            )
        found.sort(key=lambda item: (-item["score"], item["doc_id"], item["section_id"]))
        found = found[:6]
        conflicts = _version_conflicts(found)
        return {
            "ok": True,
            "tool": "search_documents",
            "arguments": arguments if arguments is not None else {"query": query},
            "query": query,
            "terms": terms,
            "match_count": len(found),
            "results": found,
            "version_conflicts": conflicts,
            "note": "结果不含正文。引用前按 section_id 调用 read_document。",
        }

    def read(self, section_id, arguments=None):
        section = self.by_id.get(section_id)
        if section is None:
            return {
                "ok": False,
                "tool": "read_document",
                "arguments": arguments if arguments is not None else {"section_id": section_id},
                "error": "section_not_found",
                "section_id": section_id,
            }
        return {
            "ok": True,
            "tool": "read_document",
            "arguments": arguments if arguments is not None else {"section_id": section_id},
            "section_id": section["section_id"],
            "doc_id": section["doc_id"],
            "title": section["title"],
            "version_date": section["version_date"],
            "heading": section["heading"],
            "text": section["text"],
        }


def _split_document(document):
    chapter = document["title"]
    heading = chapter
    buffer = []
    chunks = []

    def flush():
        text = "\n".join(buffer).strip()
        buffer.clear()
        if len(text) < 8 or heading == "目录":
            return
        chunks.append(
            {
                "doc_id": document["doc_id"],
                "title": document["title"],
                "source": document.get("source") or "",
                "version_date": document["version_date"],
                "heading": heading,
                "text": text,
            }
        )

    for raw in document["text"].splitlines():
        line = raw.strip()
        if line.startswith("# ") and not line.startswith("## "):
            continue
        if line.startswith("## "):
            flush()
            chapter = line[3:].strip()
            heading = chapter
            continue
        if line.startswith("### "):
            flush()
            heading = chapter + " / " + line[4:].strip()
            continue
        if _ARTICLE.match(line):
            flush()
            heading = chapter + " / " + line[:18]
            buffer.append(raw)
            continue
        buffer.append(raw)
    flush()
    for index, chunk in enumerate(chunks, start=1):
        chunk["section_id"] = "%s:%d" % (document["doc_id"], index)
    return chunks


def _score(section, terms):
    heading = section["heading"]
    body = section["text"]
    score = 0
    matched = []
    for term in terms:
        in_heading = term in heading
        in_body = term in body
        if in_heading or in_body:
            score += len(term) + (5 if in_heading else 0)
            matched.append(term)
    return score, matched


def _version_conflicts(results):
    grouped = {}
    for item in results:
        grouped.setdefault(item["heading"], set()).add(item["doc_id"])
    return [heading for heading, doc_ids in grouped.items() if len(doc_ids) > 1]
