"""RRF 之后的重排。未配置或调用失败时保留 RRF 顺序。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from src.retrieval.settings import get_settings


def rerank_hits(query, hits, top_k):
    settings = get_settings()
    if not hits:
        return [], "no_candidates", ""
    if not _enabled(settings):
        return hits[:top_k], "disabled", ""
    documents = [hit.text for hit in hits[: settings.RERANK_CANDIDATE_TOP_K]]
    try:
        ranked = _request(settings, query, documents, len(documents))
    except Exception as exc:
        return hits[:top_k], "fallback_to_rrf", str(exc)
    ordered = _take(hits, documents, ranked, settings.RERANK_MIN_SCORE)
    if ordered:
        return ordered[:top_k], "success", ""
    if ranked and settings.RERANK_MIN_SCORE > 0:
        ordered = _take(hits, documents, ranked, 0.0)
        if ordered:
            return ordered[:top_k], "below_threshold", "top_score=%.4f" % ranked[0][1]
    return hits[:top_k], "fallback_to_rrf", "empty_rerank_result"


def _take(hits, documents, ranked, min_score):
    ordered = []
    seen = set()
    for index, score in ranked:
        if index < 0 or index >= len(documents) or index in seen:
            continue
        if min_score > 0 and score < min_score:
            continue
        seen.add(index)
        hit = hits[index]
        hit.score = score
        hit.score_type = "rerank"
        hit.metadata["rerank_score"] = score
        hit.metadata["rerank_status"] = "success"
        hit.metadata["score_source"] = "rerank"
        ordered.append(hit)
    return ordered


def _enabled(settings):
    flag = settings.RERANK_ENABLED
    has_credentials = bool(settings.RERANK_BASE_URL and _api_key(settings))
    if settings.RERANK_ENABLED_EXPLICIT:
        return flag and has_credentials
    return has_credentials


def _api_key(settings):
    return settings.RERANK_API_KEY or settings.DASHSCOPE_API_KEY or settings.QWEN_API_KEY


def _request(settings, query, documents, top_n):
    if "compatible-api" in settings.RERANK_BASE_URL:
        body = {
            "model": settings.RERANK_MODEL,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }
    else:
        body = {
            "model": settings.RERANK_MODEL,
            "input": {"query": query, "documents": documents},
            "parameters": {
                "return_documents": settings.RERANK_RETURN_DOCUMENTS,
                "top_n": top_n,
            },
        }
    request = urllib.request.Request(
        settings.RERANK_BASE_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + _api_key(settings), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.RERANK_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:180]
        raise RuntimeError("HTTP %s %s" % (exc.code, detail)) from exc
    rows = payload.get("results") or (payload.get("output") or {}).get("results") or []
    parsed = []
    for row in rows:
        parsed.append((int(row.get("index") or 0), float(row.get("relevance_score") or row.get("score") or 0)))
    parsed.sort(key=lambda item: -item[1])
    return parsed
