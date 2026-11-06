"""检索子代理。LangGraph 编排检索和阅读，不重试，只把状态交回主代理。"""

from __future__ import annotations

from src.retrieval.graph import run_retrieval_graph


class RetrievalAgent:
    def __init__(self, runtime, model):
        self.runtime = runtime
        self.model = model

    def run(self, question, arguments=None):
        from src.harness.tracing import trace_run

        question = str(question or "").strip()
        box = {}

        def _invoke():
            state = run_retrieval_graph(self.runtime, self.model, question)
            status = state.get("status") or "insufficient_evidence"
            findings = state.get("findings") if isinstance(state.get("findings"), list) else []
            gaps = [str(item) for item in state.get("gaps") or []]
            confirmation = str(state.get("confirmation_needed") or "")
            box["result"] = _brief(
                arguments,
                status,
                findings,
                gaps,
                confirmation,
                state.get("trace") or [],
                ok=status != "tool_error",
            )
            return {"status": status, "findings": len(findings)}

        trace_run(
            "retrieval.turn",
            "chain",
            _invoke,
            {"question": question},
            {"agent": "retrieval"},
        )
        return box["result"]


def _brief(arguments, status, findings, gaps, confirmation, trace, ok):
    error = ""
    if status == "tool_error":
        error = "；".join(gaps) or "检索工具失败"
    return {
        "ok": ok,
        "tool": "consult_retrieval",
        "arguments": arguments if arguments is not None else {},
        "status": status,
        "findings": findings,
        "gaps": gaps,
        "confirmation_needed": confirmation,
        "retrieval_trace": trace,
        "error": error,
    }
