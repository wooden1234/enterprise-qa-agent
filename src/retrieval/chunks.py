"""把制度章节写成知识库块。块编号在写入索引前必须唯一。"""

from __future__ import annotations

from src.harness.knowledge.index import SectionIndex


def build_chunks(index=None):
    index = index or SectionIndex.load()
    chunks = []
    for position, section in enumerate(index.sections):
        chunk_id = "%s:policy:%06d" % (section["doc_id"], position)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "text": section["text"],
                "metadata": {
                    "doc_id": section["doc_id"],
                    "document_name": section["title"],
                    "source": section.get("source") or "",
                    "version_date": section["version_date"],
                    "section_id": section["section_id"],
                    "section": section["heading"],
                    "chunk_index": position,
                    "chunk_kind": "policy_section",
                    "category": "policy",
                    "ingested_at": "",
                },
            }
        )
    validate_unique_chunk_ids(chunks)
    return chunks


def validate_unique_chunk_ids(chunks):
    seen = set()
    duplicates = set()
    missing = []
    for position, chunk in enumerate(chunks):
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            missing.append(position)
            continue
        if chunk_id in seen:
            duplicates.add(chunk_id)
        seen.add(chunk_id)
    if missing:
        raise ValueError("chunk_id 缺失：%s" % missing[:10])
    if duplicates:
        raise ValueError("chunk_id 重复：%s" % sorted(duplicates)[:10])
