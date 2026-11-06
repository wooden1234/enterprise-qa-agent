"""读取合成制度。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCUMENTS = DATA / "documents.json"
RULES = DATA / "rules.md"


def load_documents():
    payload = json.loads(DOCUMENTS.read_text(encoding="utf-8"))
    documents = []
    for item in payload["documents"]:
        source = item.get("source")
        if not source:
            raise ValueError(item.get("doc_id", "") + " 缺少 source")
        path = DATA / source
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(source + " 没有正文")
        loaded = dict(item)
        loaded["text"] = text
        documents.append(loaded)
    if not documents:
        raise ValueError("documents.json 没有制度")
    return documents


def load_rules():
    return RULES.read_text(encoding="utf-8").strip()
