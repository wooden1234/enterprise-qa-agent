"""单会话循环：选动作、执行工具、观察结果、再决定或结束。"""

from __future__ import annotations

import json

from src.harness.agent.result import RunResult
from src.harness.control.policy import enrich_citations, review_submission
from src.harness.session.surface import messages_for_llm
from src.harness.session.types import EventDraft, new_id
from src.harness.tools.scheduler import execute_tool_calls, summarize
from src.llm import system_prompt

_MAX_STEPS = 8


class Agent:
    def __init__(self, store, model, runtime, *, max_steps=_MAX_STEPS, user_id="default", tenant_id="default"):
        self.store = store
        self.model = model
        self.runtime = runtime
        self.max_steps = max_steps
        self.user_id = user_id or "default"
        self.tenant_id = tenant_id or "default"
        self.session_id = new_id()

    def prompt(self, question, *, history=None, run_id=""):
        from src.harness.tracing import trace_run

        box = {}

        def _invoke():
            box["result"] = self._run_turn(question, history=history, run_id=run_id)
            result = box["result"]
            return {
                "status": result.status,
                "answer": result.answer,
                "finish_reason": result.finish_reason,
                "session_id": result.session_id,
                "run_id": result.run_id,
            }

        trace_run(
            "agent.turn",
            "chain",
            _invoke,
            {"question": question, "session_id": self.session_id},
            {"thread_id": self.session_id, "session_id": self.session_id},
        )
        return box["result"]

    def _run_turn(self, question, *, history=None, run_id=""):
        history = history or []
        run_id = run_id or new_id()
        turn = 1
        self._append("turn/start", run_id, turn, 0, {"question": question})
        for item in history:
            self._append(
                "user/message",
                run_id,
                turn,
                0,
                {"content": str(item.get("content") or ""), "role": item.get("role") or "user"},
            )
        self._append("user/message", run_id, turn, 0, {"content": "当前问题：" + question.strip()})
        self._append(
            "request/header",
            run_id,
            turn,
            0,
            {"system": self._system_prompt(), "tools": self.runtime.names(), "user_id": self.user_id},
        )
        reads = {}
        fail_counts = {}
        published = None
        reason = "incomplete"
        for step in range(1, self.max_steps + 1):
            self._append("step/start", run_id, turn, step, {"step": step})
            messages = messages_for_llm(
                self.store.load_events(),
                system=system_prompt(),
                preferences=self._preferences(),
            )
            raw, action = self._complete(messages, step)
            name = action.get("action")
            arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            basis = action.get("decision_basis") or "模型未提供决策依据"
            self._append(
                "assistant/message",
                run_id,
                turn,
                step,
                {
                    "content": raw,
                    "action": name,
                    "arguments": arguments,
                    "decision_basis": basis,
                },
            )
            if name == "submit_answer":
                review = review_submission(arguments, reads)
                if review is None:
                    published = arguments
                    reason = "completed"
                    self._append("step/end", run_id, turn, step, {"reason": reason})
                    break
                observation = {
                    "ok": False,
                    "tool": "submit_answer",
                    "type": "review",
                    "error": review,
                }
                self._append(
                    "tool/result",
                    run_id,
                    turn,
                    step,
                    {"name": "submit_answer", "summary": summarize(observation), "observation": observation},
                )
            else:
                self._execute_tool(name, arguments, turn, step, run_id, fail_counts)
                latest = self.store.load_events()[-1].data.get("observation") or {}
                if latest.get("tool") == "consult_retrieval":
                    for item in latest.get("findings") or []:
                        if item.get("section_id"):
                            reads[item["section_id"]] = item
                elif latest.get("ok") and latest.get("tool") == "read_document":
                    reads[latest["section_id"]] = latest
            if step == self.max_steps and reason != "completed":
                reason = "incomplete"
                self._append("step/end", run_id, turn, step, {"reason": reason})
                break
            self._append("step/end", run_id, turn, step, {"reason": "continue"})
        self._append("turn/end", run_id, turn, 0, {"reason": reason})
        if published is None:
            return RunResult(
                session_id=self.session_id,
                run_id=run_id,
                finish_reason=reason,
                status="incomplete",
                gaps=["达到最大步数 %d，任务未完成" % self.max_steps],
                events=self.store.load_events(),
                error="" if reason == "incomplete" else reason,
            )
        return RunResult(
            session_id=self.session_id,
            run_id=run_id,
            finish_reason="completed",
            status=published["status"],
            answer=str(published.get("answer") or ""),
            citations=enrich_citations(published, reads),
            gaps=[str(item) for item in published.get("gaps") or []],
            confirmation_needed=str(published.get("confirmation_needed") or ""),
            events=self.store.load_events(),
        )

    def _preferences(self):
        from src.memory.store import load_preferences

        return load_preferences(self.user_id, self.tenant_id)

    def _system_prompt(self):
        from src.memory.preferences import compose_system

        return compose_system(system_prompt(), self._preferences())

    def _complete(self, messages, step):
        from src.harness.tracing import trace_run

        last = messages[-1]["content"] if messages else ""
        return trace_run(
            "chat.completion",
            "llm",
            lambda: self.model.complete(messages),
            {"step": step, "model": getattr(self.model, "model_name", ""), "last_message": str(last)[:500]},
        )

    def _execute_tool(self, name, arguments, turn, step, run_id, fail_counts):
        from src.harness.tracing import trace_run

        def _call():
            execute_tool_calls(
                self.store,
                self.runtime,
                [{"name": name, "arguments": arguments}],
                turn=turn,
                step=step,
                run_id=run_id,
                fail_counts=fail_counts,
            )
            return (self.store.load_events()[-1].data.get("observation") or {})

        return trace_run(name or "tool", "tool", _call, {"arguments": arguments})

    def _append(self, event_type, run_id, turn, step, data):
        self.store.append(EventDraft(event_type=event_type, run_id=run_id, turn=turn, step=step, data=data))


def trace_from_events(events):
    trace = []
    for event in events:
        if event.event_type != "assistant/message":
            continue
        data = event.data
        trace.append(
            {
                "step": event.step,
                "action": data.get("action"),
                "arguments": data.get("arguments") or {},
                "decision_basis": data.get("decision_basis") or "",
                "observation_summary": "",
                "next_action": "",
            }
        )
    results = [event for event in events if event.event_type == "tool/result"]
    for item, event in zip(trace, results):
        item["observation_summary"] = event.data.get("summary") or ""
    for index, item in enumerate(trace[:-1]):
        item["next_action"] = trace[index + 1]["action"]
    reason = "incomplete"
    for event in events:
        if event.event_type == "turn/end":
            reason = event.data.get("reason") or reason
    if trace:
        trace[-1]["next_action"] = "finish" if reason == "completed" else "incomplete"
    return trace
