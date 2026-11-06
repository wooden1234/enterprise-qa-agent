"""检索子代理的 LangGraph。边只跟随模型刚选出的动作。"""

from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.harness.tools.scheduler import summarize
from src.llm import retrieval_system_prompt

_MAX_DECIDES = 8


class RetrievalState(TypedDict, total=False):
    question: str
    messages: list
    choice: dict
    steps: int
    reads: dict
    status: str
    findings: list
    gaps: list
    confirmation_needed: str
    trace: list
    force_stop: bool


def run_retrieval_graph(runtime, model, question):
    """每一步把工具结果交回模型，再按它选择的动作跳转。"""
    app = _compile(runtime, model)
    question = str(question or "").strip()
    state = app.invoke(
        {
            "question": question,
            "messages": [{"role": "user", "content": "当前问题：" + question}],
            "choice": {},
            "steps": 0,
            "reads": {},
            "status": "",
            "findings": [],
            "gaps": [],
            "confirmation_needed": "",
            "trace": [],
            "force_stop": False,
        },
        config={"recursion_limit": 40},
    )
    trace = list(state.get("trace") or [])
    for index, item in enumerate(trace[:-1]):
        item["next_action"] = trace[index + 1]["action"]
    if trace:
        trace[-1]["next_action"] = "finish"
    state["trace"] = trace
    return state


def _compile(runtime, model):
    def decide(state):
        steps = int(state.get("steps") or 0) + 1
        if steps > _MAX_DECIDES:
            return {"steps": steps, "force_stop": True}
        messages = [{"role": "system", "content": retrieval_system_prompt()}]
        messages.extend(state.get("messages") or [])
        _raw, action = model.complete(messages)
        convo = list(state.get("messages") or [])
        convo.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
        return {"choice": action, "steps": steps, "messages": convo, "force_stop": False}

    def search(state):
        arguments = (state.get("choice") or {}).get("arguments") or {}
        observation = runtime.resolve("search_documents").handler(arguments)
        return _after_tool(state, observation)

    def read(state):
        arguments = (state.get("choice") or {}).get("arguments") or {}
        observation = runtime.resolve("read_document").handler(arguments)
        reads = dict(state.get("reads") or {})
        if observation.get("ok") and observation.get("section_id"):
            reads[observation["section_id"]] = observation
        update = _after_tool(state, observation)
        update["reads"] = reads
        return update

    def reject(state):
        choice = state.get("choice") or {}
        observation = {
            "ok": False,
            "tool": choice.get("action") or "unknown",
            "error": "检索子代理只能检索、阅读或提交发现",
        }
        return _after_tool(state, observation)

    def finish(state):
        arguments = (state.get("choice") or {}).get("arguments") or {}
        status = str(arguments.get("status") or "insufficient_evidence")
        findings = _enrich(arguments.get("findings"), state.get("reads") or {})
        gaps = [str(item) for item in arguments.get("gaps") or []]
        confirmation = str(arguments.get("confirmation_needed") or "")
        update = _terminal(status, findings, gaps, confirmation)
        update["trace"] = _append_submit(state, status, arguments)
        return update

    def stop(state):
        return _terminal(
            "insufficient_evidence",
            [],
            ["检索子代理达到最大步数 %d，没有交回发现" % _MAX_DECIDES],
            "",
        )

    def route(state):
        if state.get("force_stop"):
            return "stop"
        action = str((state.get("choice") or {}).get("action") or "")
        if action == "search_documents":
            return "search"
        if action == "read_document":
            return "read"
        if action == "submit_findings":
            return "finish"
        return "reject"

    graph = StateGraph(RetrievalState)
    graph.add_node("decide", decide)
    graph.add_node("search", search)
    graph.add_node("read", read)
    graph.add_node("reject", reject)
    graph.add_node("finish", finish)
    graph.add_node("stop", stop)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges(
        "decide",
        route,
        {"search": "search", "read": "read", "finish": "finish", "reject": "reject", "stop": "stop"},
    )
    graph.add_edge("search", "decide")
    graph.add_edge("read", "decide")
    graph.add_edge("reject", "decide")
    graph.add_edge("finish", END)
    graph.add_edge("stop", END)
    return graph.compile()


def _after_tool(state, observation):
    convo = list(state.get("messages") or [])
    convo.append({"role": "user", "content": "工具结果：\n" + json.dumps(observation, ensure_ascii=False)})
    return {"messages": convo, "trace": _append_tool(state, observation)}


def _append_tool(state, observation):
    choice = state.get("choice") or {}
    trace = list(state.get("trace") or [])
    trace.append(
        {
            "step": len(trace) + 1,
            "action": choice.get("action"),
            "arguments": choice.get("arguments") or {},
            "decision_basis": choice.get("decision_basis") or "",
            "observation_summary": summarize(observation),
            "next_action": "",
        }
    )
    return trace


def _append_submit(state, status, arguments):
    choice = state.get("choice") or {}
    trace = list(state.get("trace") or [])
    trace.append(
        {
            "step": len(trace) + 1,
            "action": "submit_findings",
            "arguments": {
                "status": status,
                "gaps": arguments.get("gaps") or [],
                "confirmation_needed": arguments.get("confirmation_needed") or "",
            },
            "decision_basis": choice.get("decision_basis") or "",
            "observation_summary": "交回状态 " + status,
            "next_action": "",
        }
    )
    return trace


def _terminal(status, findings, gaps, confirmation):
    return {
        "status": status,
        "findings": findings,
        "gaps": gaps,
        "confirmation_needed": confirmation,
    }


def _enrich(findings, reads):
    if not isinstance(findings, list):
        return []
    cleaned = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section_id") or "")
        source = reads.get(section_id) or {}
        cleaned.append(
            {
                "doc_id": item.get("doc_id") or source.get("doc_id"),
                "title": item.get("title") or source.get("title"),
                "version_date": item.get("version_date") or source.get("version_date"),
                "heading": item.get("heading") or source.get("heading"),
                "section_id": section_id,
                "quote": str(item.get("quote") or ""),
                "text": source.get("text") or item.get("text") or "",
            }
        )
    return cleaned
