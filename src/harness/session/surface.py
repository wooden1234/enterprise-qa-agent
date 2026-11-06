"""把事件投影成下一轮要发给模型的消息。"""

from __future__ import annotations

import json

from src.memory.preferences import compose_system


def messages_for_llm(events, system="", preferences=None):
    """每次拼接都把长期偏好接在稳定系统提示词后面。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": compose_system(system, preferences)})
    for event in events:
        data = event.data or {}
        if event.event_type == "user/message":
            role = data.get("role") or "user"
            if role not in ("user", "assistant"):
                role = "user"
            messages.append({"role": role, "content": data.get("content") or ""})
        elif event.event_type == "assistant/message":
            messages.append({"role": "assistant", "content": data.get("content") or ""})
        elif event.event_type == "tool/result":
            messages.append(
                {
                    "role": "user",
                    "content": "工具结果：\n" + json.dumps(_for_prompt(data.get("observation") or {}), ensure_ascii=False),
                }
            )
    return messages


def _for_prompt(observation):
    """交给主模型的发现只保留引用字段，正文留在审核用的已读记录里。"""
    if observation.get("tool") != "consult_retrieval":
        return observation
    copied = dict(observation)
    findings = []
    for item in observation.get("findings") or []:
        if not isinstance(item, dict):
            findings.append(item)
            continue
        findings.append({key: value for key, value in item.items() if key != "text"})
    copied["findings"] = findings
    return copied
