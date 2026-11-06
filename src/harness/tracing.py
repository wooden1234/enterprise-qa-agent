"""LangSmith 追踪。未打开或未安装时，问答循环照常执行。"""

from __future__ import annotations

import os


def tracing_enabled():
    from src.retrieval.settings import load_env_file

    load_env_file()
    os.environ.setdefault("LANGSMITH_PROJECT", "enterprise-qa-agent")
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        return False
    return bool(os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"))


def trace_run(name, run_type, func, inputs=None, metadata=None):
    if not tracing_enabled():
        return func()
    state = {}

    def _call(payload=None):
        state["value"] = func()
        return state["value"]

    try:
        from langsmith import traceable

        traced = traceable(name=name, run_type=run_type, metadata=metadata or {})(_call)
        return traced(inputs or {})
    except Exception:
        if "value" in state:
            return state["value"]
        return func()


def flush_traces():
    if not tracing_enabled():
        return
    try:
        from langsmith.run_trees import get_cached_client

        get_cached_client().flush()
    except Exception:
        return
