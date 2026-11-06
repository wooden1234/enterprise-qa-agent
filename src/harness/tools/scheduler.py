"""按模型给出的顺序执行工具，并把结果写成 tool/result 事件。"""

from __future__ import annotations

from src.harness.session.types import EventDraft


def execute_tool_calls(store, runtime, calls, *, turn, step, run_id, fail_counts):
    results = []
    for call in calls:
        name = call.get("name") or ""
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        definition = runtime.resolve(name)
        if definition is None:
            observation = {
                "ok": False,
                "tool": name or "unknown",
                "arguments": arguments,
                "error": "未知工具",
            }
        else:
            observation = definition.handler(arguments)
        if not observation.get("ok"):
            key = (name, _stable(arguments))
            fail_counts[key] = fail_counts.get(key, 0) + 1
            if fail_counts[key] >= 2:
                observation = dict(observation)
                observation["hint"] = "相同调用已失败两次。请提交 tool_error，不要编造答案。"
        summary = summarize(observation)
        store.append(
            EventDraft(
                event_type="tool/result",
                run_id=run_id,
                turn=turn,
                step=step,
                data={"name": name, "summary": summary, "observation": observation},
            )
        )
        results.append(observation)
    return results


def summarize(observation):
    if observation.get("type") == "review":
        return "提交未通过：" + str(observation.get("error") or "")
    if not observation.get("ok"):
        text = "失败：" + str(observation.get("error") or "未知错误")
        if observation.get("hint"):
            text += "；" + observation["hint"]
        return text
    if observation.get("tool") == "search_documents":
        ids = ["%s/%s" % (item["doc_id"], item["heading"]) for item in observation.get("results") or []]
        if not ids:
            return "没有命中"
        text = "命中 " + "；".join(ids)
        conflicts = observation.get("version_conflicts") or []
        if conflicts:
            text += "。同一章节有多个版本：" + "、".join(conflicts)
        return text
    if observation.get("tool") == "read_document":
        return "已读取 %s %s" % (observation.get("doc_id"), observation.get("heading"))
    if observation.get("tool") == "consult_retrieval":
        text = "检索子代理：" + str(observation.get("status") or "")
        gaps = "；".join(str(item) for item in observation.get("gaps") or [])
        if gaps:
            text += "。" + gaps
        found = ["%s/%s" % (item.get("doc_id"), item.get("heading") or "") for item in observation.get("findings") or []]
        if found:
            text += "。读到 " + "；".join(found)
        return text
    return "已返回"


def _stable(arguments):
    parts = []
    for key in sorted(arguments):
        parts.append("%s=%s" % (key, arguments[key]))
    return "&".join(parts)
