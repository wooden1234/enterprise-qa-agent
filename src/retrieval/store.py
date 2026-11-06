"""本地知识库：chunks.jsonl 保存切片和元数据，vectors.json 保存嵌入。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.retrieval.chunks import build_chunks
from src.retrieval.embeddings import embed_texts
from src.retrieval.settings import CHUNKS_PATH, VECTORS_PATH, get_settings

_INGEST_TZ = timezone(timedelta(hours=8))


def ingest_timestamp():
    return datetime.now(_INGEST_TZ).isoformat(timespec="seconds")


def attach_ingest_time(chunks, ingested_at=None):
    """同一批切片共用一个入库时间，写在 metadata JSON 里。"""
    stamped = ingested_at or ingest_timestamp()
    for chunk in chunks:
        metadata = chunk.setdefault("metadata", {})
        metadata["ingested_at"] = stamped
    return stamped


def write_chunks(chunks=None, ingested_at=None):
    chunks = chunks if chunks is not None else build_chunks()
    attach_ingest_time(chunks, ingested_at)
    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(chunk, ensure_ascii=False) for chunk in chunks]
    CHUNKS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CHUNKS_PATH


def load_chunk_file():
    if not CHUNKS_PATH.is_file():
        return []
    chunks = []
    for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))
    return chunks


def write_vectors(chunks, vectors, model):
    payload = {
        "model": model,
        "dim": len(vectors[0]) if vectors else 0,
        "items": [
            {"chunk_id": chunk["chunk_id"], "vector": vector}
            for chunk, vector in zip(chunks, vectors)
        ],
    }
    VECTORS_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return VECTORS_PATH


def load_chunks():
    from src.retrieval.pgstore import fetch_chunks

    stored = fetch_chunks()
    if stored:
        return stored
    return load_chunk_file()


def load_vectors():
    if not VECTORS_PATH.is_file():
        return {}
    payload = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    return {
        "model": payload.get("model") or "",
        "dim": payload.get("dim") or 0,
        "vectors": {item["chunk_id"]: item["vector"] for item in payload.get("items") or []},
    }


def build_vector_index():
    settings = get_settings()
    chunks = build_chunks()
    write_chunks(chunks)
    vectors = embed_texts([chunk["text"] for chunk in chunks], settings)
    path = write_vectors(chunks, vectors, settings.EMBEDDING_MODEL)
    return {"chunks": len(chunks), "dim": len(vectors[0]) if vectors else 0, "path": str(path)}
