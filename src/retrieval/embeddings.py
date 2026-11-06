"""OpenAI 兼容嵌入。凭证顺序与 fin-harness/retrieval/clients/embeddings.py 相同。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from src.retrieval.settings import get_settings


class EmbeddingError(RuntimeError):
    pass


def resolve_credentials(settings=None):
    settings = settings or get_settings()
    provider = settings.EMBEDDING_PROVIDER.lower()
    api_key = settings.EMBEDDING_API_KEY
    if not api_key and provider == "dashscope":
        api_key = settings.QWEN_API_KEY or settings.DASHSCOPE_API_KEY
    base_url = settings.EMBEDDING_BASE_URL or (settings.QWEN_BASE_URL if provider == "dashscope" else "")
    if not api_key:
        raise EmbeddingError("未配置 EMBEDDING_API_KEY / QWEN_API_KEY / DASHSCOPE_API_KEY")
    if not base_url:
        raise EmbeddingError("未配置 EMBEDDING_BASE_URL / QWEN_BASE_URL")
    return api_key, base_url.rstrip("/"), settings.EMBEDDING_MODEL


def embed_texts(texts, settings=None):
    settings = settings or get_settings()
    api_key, base_url, model = resolve_credentials(settings)
    batch_size = settings.EMBEDDING_BATCH_SIZE or (8 if settings.EMBEDDING_PROVIDER == "xfyun" else 10)
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(_embed_batch(base_url, api_key, model, batch))
    return vectors


def _embed_batch(base_url, api_key, model, texts):
    url = base_url + "/embeddings"
    body = {"model": model, "input": texts if len(texts) > 1 else texts[0]}
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise EmbeddingError("嵌入请求失败：HTTP %s %s" % (exc.code, detail)) from exc
    rows = payload.get("data") or []
    rows.sort(key=lambda item: item.get("index") or 0)
    vectors = [item.get("embedding") for item in rows]
    if len(vectors) != len(texts) or any(not isinstance(item, list) for item in vectors):
        raise EmbeddingError("嵌入响应数量与输入不一致")
    return vectors
