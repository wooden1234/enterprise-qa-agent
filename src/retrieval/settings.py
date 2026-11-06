"""读取与 fin-harness 相同的嵌入和重排变量。不写密钥。"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "data" / "kb"
CHUNKS_PATH = KB_DIR / "chunks.jsonl"
VECTORS_PATH = KB_DIR / "vectors.json"


def load_env_file(path=None):
    candidate = Path(path) if path else _default_env_file()
    if candidate is None or not candidate.is_file():
        return
    for line in candidate.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _default_env_file():
    configured = os.environ.get("ENV_FILE") or ""
    if configured:
        return Path(configured)
    local = ROOT / ".env"
    if local.is_file():
        return local
    return None


def _text(name, default=""):
    return os.environ.get(name, default).strip()


def _int(name, default):
    raw = _text(name)
    if not raw:
        return default
    return int(raw)


def _float(name, default):
    raw = _text(name)
    if not raw:
        return default
    return float(raw)


class Settings:
    def __init__(self):
        load_env_file()
        self.EMBEDDING_PROVIDER = _text("EMBEDDING_PROVIDER", "dashscope")
        self.EMBEDDING_API_KEY = _text("EMBEDDING_API_KEY")
        self.EMBEDDING_MODEL = _text("EMBEDDING_MODEL", "text-embedding-v2")
        self.EMBEDDING_BASE_URL = _text("EMBEDDING_BASE_URL")
        self.EMBEDDING_DIM = _int("EMBEDDING_DIM", 1536)
        self.EMBEDDING_BATCH_SIZE = _int("EMBEDDING_BATCH_SIZE", 0)
        self.QWEN_API_KEY = _text("QWEN_API_KEY")
        self.QWEN_BASE_URL = _text("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.DASHSCOPE_API_KEY = _text("DASHSCOPE_API_KEY")
        self.RERANK_ENABLED_EXPLICIT = bool(_text("RERANK_ENABLED"))
        self.RERANK_ENABLED = _text("RERANK_ENABLED", "false").lower() in {"1", "true", "yes"}
        self.RERANK_PROVIDER = _text("RERANK_PROVIDER", "dashscope")
        self.RERANK_API_KEY = _text("RERANK_API_KEY")
        self.RERANK_MODEL = _text("RERANK_MODEL", "qwen3-rerank")
        self.RERANK_BASE_URL = _text("RERANK_BASE_URL")
        self.RERANK_CANDIDATE_TOP_K = _int("RERANK_CANDIDATE_TOP_K", 20)
        self.RERANK_MIN_SCORE = _float("RERANK_MIN_SCORE", 0.0)
        self.RERANK_TIMEOUT_SEC = _int("RERANK_TIMEOUT_SEC", 30)
        self.RERANK_RETURN_DOCUMENTS = _text("RERANK_RETURN_DOCUMENTS", "true").lower() in {"1", "true", "yes"}
        self.VECTOR_SIMILARITY_THRESHOLD = _float("VECTOR_SIMILARITY_THRESHOLD", 0.35)
        self.RETRIEVAL_CANDIDATE_TOP_K = _int("RETRIEVAL_CANDIDATE_TOP_K", 20)
        self.RRF_K = _int("RRF_K", 60)
        self.BM25_K1 = _float("BM25_K1", 1.5)
        self.BM25_B = _float("BM25_B", 0.75)
        self.PGVECTOR_DATABASE_URL = _text("PGVECTOR_DATABASE_URL")


def get_settings():
    return Settings()
