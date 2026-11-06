"""检索链路：向量召回、BM25 召回、RRF 融合、重排。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.harness.knowledge.index import SectionIndex
from src.retrieval.bm25 import BM25Okapi, tokenize
from src.retrieval.settings import get_settings
from src.retrieval.store import load_chunks, load_vectors
from src.tools import content_terms

_BM25_CACHE = {"key": None, "model": None}


@dataclass
class RetrievalHit:
    text: str
    score: float
    metadata: dict
    node_id: str = ""
    category: str = "policy"
    score_type: str = "unknown"


def search_policy(query, top_k=6, arguments=None):
    """返回与 search_documents 相同的观察结构，并附带四步检索轨迹。"""
    settings = get_settings()
    chunks = load_chunks()
    if not chunks:
        payload = SectionIndex.load().search(query, arguments)
        payload["retrieval"] = {"mode": "section_index", "abstained": payload["match_count"] == 0}
        return payload
    stored = load_vectors()
    vectors = stored.get("vectors") or {}
    candidate_k = max(settings.RETRIEVAL_CANDIDATE_TOP_K, top_k * 4, settings.RERANK_CANDIDATE_TOP_K)
    vector_hits, vector_error = _vector_hits(query, chunks, vectors, candidate_k, settings)
    bm25_hits = _bm25_hits(query, chunks, candidate_k, settings)
    if not vector_hits and not bm25_hits:
        return _empty(query, arguments, vector_error, len(bm25_hits))
    fused = _rrf_fuse(
        [("vector", vector_hits), ("bm25", bm25_hits)],
        top_k=max(top_k, settings.RERANK_CANDIDATE_TOP_K),
        rrf_k=settings.RRF_K,
    )
    from src.retrieval.rerank import rerank_hits

    final_hits, rerank_status, rerank_error = rerank_hits(query, fused, top_k)
    if not final_hits:
        return _empty(query, arguments, vector_error or rerank_error, len(bm25_hits), rerank_status)
    results = [_public_result(hit) for hit in final_hits]
    return {
        "ok": True,
        "tool": "search_documents",
        "arguments": arguments if arguments is not None else {"query": query},
        "query": query,
        "terms": content_terms(query),
        "match_count": len(results),
        "results": results,
        "version_conflicts": _version_conflicts(results),
        "retrieval": {
            "mode": "vector_bm25_rrf_rerank",
            "vector_hits": len(vector_hits),
            "bm25_hits": len(bm25_hits),
            "rrf_hits": len(fused),
            "rerank_status": rerank_status,
            "rerank_error": rerank_error,
            "vector_error": vector_error,
            "abstained": False,
        },
        "note": "结果不含正文。引用前按 section_id 调用 read_document。",
    }


def _vector_hits(query, chunks, vectors, top_k, settings):
    if not vectors:
        return [], "vectors_missing"
    try:
        from src.retrieval.embeddings import embed_texts

        query_vector = embed_texts([query])[0]
    except Exception as exc:
        return [], str(exc)
    from src.retrieval.pgstore import search_by_vector

    stored_hits = search_by_vector(query_vector, top_k, settings.VECTOR_SIMILARITY_THRESHOLD)
    if stored_hits is not None:
        hits = []
        for row in stored_hits:
            chunk = {"chunk_id": row["chunk_id"], "text": row["text"], "metadata": row["metadata"]}
            metadata = _hit_metadata(chunk)
            metadata["vector_score"] = row["score"]
            hits.append(
                RetrievalHit(
                    text=_search_text(chunk),
                    score=row["score"],
                    metadata=metadata,
                    node_id=row["chunk_id"],
                    score_type="vector",
                )
            )
        return hits, ""
    hits = []
    for chunk in chunks:
        vector = vectors.get(chunk["chunk_id"])
        if not vector:
            continue
        score = _cosine(query_vector, vector)
        if score < settings.VECTOR_SIMILARITY_THRESHOLD:
            continue
        metadata = _hit_metadata(chunk)
        metadata["vector_score"] = score
        hits.append(
            RetrievalHit(
                text=_search_text(chunk),
                score=score,
                metadata=metadata,
                node_id=chunk["chunk_id"],
                score_type="vector",
            )
        )
    hits.sort(key=lambda item: -item.score)
    return hits[:top_k], ""


def _bm25_hits(query, chunks, top_k, settings):
    model = _bm25_model(chunks, settings.BM25_K1, settings.BM25_B)
    scores = model.scores(tokenize(query))
    ranked = []
    for chunk, score in zip(chunks, scores):
        if score <= 0:
            continue
        metadata = _hit_metadata(chunk)
        metadata["bm25_score"] = score
        metadata["bm25_backend"] = "local"
        ranked.append(
            RetrievalHit(
                text=_search_text(chunk),
                score=score,
                metadata=metadata,
                node_id=chunk["chunk_id"],
                score_type="bm25",
            )
        )
    ranked.sort(key=lambda item: -item.score)
    return ranked[:top_k]


def _bm25_model(chunks, k1, b):
    key = ("jieba-domain-v1", len(chunks), chunks[0]["chunk_id"], chunks[-1]["chunk_id"], k1, b)
    if _BM25_CACHE["key"] != key:
        documents = [tokenize(_search_text(chunk)) for chunk in chunks]
        _BM25_CACHE["key"] = key
        _BM25_CACHE["model"] = BM25Okapi(documents, k1=k1, b=b)
    return _BM25_CACHE["model"]


def _rrf_fuse(ranked_lists, top_k, rrf_k):
    scores = {}
    by_key = {}
    ranks = {}
    for list_name, ranked in ranked_lists:
        for rank, hit in enumerate(ranked, 1):
            key = hit.node_id
            current = by_key.get(key)
            if current is None:
                current = RetrievalHit(
                    text=hit.text,
                    score=0.0,
                    metadata=dict(hit.metadata),
                    node_id=hit.node_id,
                    score_type="rrf",
                )
                by_key[key] = current
            else:
                current.metadata.update(hit.metadata)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            ranks.setdefault(key, {})[list_name] = rank
    fused = []
    for key, hit in by_key.items():
        hit.score = scores[key]
        hit.metadata["rrf_score"] = hit.score
        hit.metadata["score_source"] = "rrf"
        if "vector" in ranks[key]:
            hit.metadata["vector_rank"] = ranks[key]["vector"]
        if "bm25" in ranks[key]:
            hit.metadata["bm25_rank"] = ranks[key]["bm25"]
        fused.append(hit)
    fused.sort(key=lambda item: -item.score)
    return fused[:top_k]


def _empty(query, arguments, vector_error, bm25_hits, rerank_status="not_run"):
    return {
        "ok": True,
        "tool": "search_documents",
        "arguments": arguments if arguments is not None else {"query": query},
        "query": query,
        "terms": content_terms(query),
        "match_count": 0,
        "results": [],
        "version_conflicts": [],
        "retrieval": {
            "mode": "vector_bm25_rrf_rerank",
            "vector_hits": 0,
            "bm25_hits": bm25_hits,
            "rrf_hits": 0,
            "rerank_status": rerank_status,
            "vector_error": vector_error,
            "abstained": True,
            "abstain_reason": "no_hit",
        },
        "note": "结果不含正文。引用前按 section_id 调用 read_document。",
    }


def _public_result(hit):
    meta = hit.metadata
    document_name = meta.get("document_name") or meta.get("title") or ""
    section = meta.get("section") or meta.get("heading") or ""
    result = {
        "section_id": meta["section_id"],
        "doc_id": meta["doc_id"],
        "title": document_name,
        "version_date": meta["version_date"],
        "heading": section,
        "score": round(hit.score, 4),
        "score_type": hit.score_type,
        "chunk_id": meta["chunk_id"],
        "metadata": _stored_metadata(meta),
    }
    for key in ("vector_rank", "bm25_rank", "rrf_score", "vector_score", "bm25_score", "rerank_score"):
        if key in meta:
            value = meta[key]
            result[key] = round(value, 4) if isinstance(value, float) else value
    return result


def _version_conflicts(results):
    grouped = {}
    for item in results:
        grouped.setdefault(item["heading"], set()).add(item["doc_id"])
    return [heading for heading, doc_ids in grouped.items() if len(doc_ids) > 1]


def _chunk_metadata(chunk):
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict) and metadata.get("section_id"):
        return metadata
    return chunk


def _hit_metadata(chunk):
    metadata = dict(_chunk_metadata(chunk))
    metadata["chunk_id"] = chunk["chunk_id"]
    metadata.pop("text", None)
    return metadata


def _stored_metadata(meta):
    return {
        "doc_id": meta.get("doc_id") or "",
        "document_name": meta.get("document_name") or meta.get("title") or "",
        "source": meta.get("source") or "",
        "version_date": meta.get("version_date") or "",
        "section_id": meta.get("section_id") or "",
        "section": meta.get("section") or meta.get("heading") or "",
        "chunk_index": meta.get("chunk_index"),
        "chunk_kind": meta.get("chunk_kind") or "",
        "category": meta.get("category") or "",
        "ingested_at": meta.get("ingested_at") or "",
    }


def _search_text(chunk):
    metadata = _chunk_metadata(chunk)
    section = metadata.get("section") or metadata.get("heading") or ""
    return "%s\n%s" % (section, chunk.get("text") or "")


def _cosine(left, right):
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)
