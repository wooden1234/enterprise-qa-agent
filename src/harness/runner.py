"""把会话、模型和知识库工具装成一次问答。"""

from __future__ import annotations

import time

from src.harness.agent.loop import Agent, trace_from_events
from src.harness.knowledge.tools import planner_runtime
from src.harness.session.store import MemorySessionStore
from src.scripted import ScriptedModel


def run(request, model=None):
    if not isinstance(request, dict):
        raise ValueError("input must be a JSON object")
    question = request.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    history = request.get("history") or []
    if not isinstance(history, list):
        raise ValueError("history must be a list")
    max_steps = request.get("max_steps", 8)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 12:
        raise ValueError("max_steps must be an integer from 1 to 12")
    fail_tool = request.get("simulate_tool_failure") or ""
    if fail_tool and fail_tool not in ("search_documents", "read_document"):
        raise ValueError("simulate_tool_failure must be search_documents or read_document")
    user_id = request.get("user_id", "default")
    tenant_id = request.get("tenant_id", "default")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    from src.retrieval.settings import load_env_file

    load_env_file()
    model = model or ScriptedModel()
    started = time.time()
    agent = Agent(
        MemorySessionStore(),
        model,
        planner_runtime(model, fail_tool=fail_tool),
        max_steps=max_steps,
        user_id=user_id.strip(),
        tenant_id=tenant_id.strip(),
    )
    result = agent.prompt(question, history=history)
    payload = {
        "status": result.status,
        "answer": result.answer,
        "citations": result.citations,
        "gaps": result.gaps,
        "confirmation_needed": result.confirmation_needed,
        "question": question.strip(),
        "trace": trace_from_events(result.events),
        "events": [event.to_dict() for event in result.events],
        "finish_reason": result.finish_reason,
        "session_id": result.session_id,
        "run_id": result.run_id,
        "mode": getattr(model, "mode", ""),
        "model": getattr(model, "model_name", getattr(model, "mode", "")),
        "max_steps": max_steps,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    usage = getattr(model, "usage", None) or {}
    if usage.get("prompt_tokens") or usage.get("completion_tokens"):
        payload["usage"] = {
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
        }
    from src.harness.tracing import flush_traces

    flush_traces()
    return payload
