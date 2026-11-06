"""长期偏好白名单，以及拼进系统提示词的文本。"""

from __future__ import annotations

PREFERENCE_KEYS = {
    "response_language": ("zh-CN", "en-US"),
    "response_detail_level": ("brief", "standard", "detailed"),
    "citation_preference": ("always", "when_available", "never"),
}


def preference_block(preferences):
    """把已保存的长期偏好格式化成一段。没有偏好时返回空字符串。"""
    kept = {}
    for key, value in dict(preferences or {}).items():
        if value is None or key not in PREFERENCE_KEYS:
            continue
        kept[key] = value
    if not kept:
        return ""
    lines = "\n".join("- %s=%s" % (key, kept[key]) for key in sorted(kept))
    return (
        "[用户长期偏好]\n"
        + lines
        + "\n回答默认遵守这些长期偏好。"
        "用户这次使用的语言或打招呼不改变回答方式。"
        "该偏好适用于问候、闲聊、澄清、错误说明和制度回答。"
    )


def compose_system(system, preferences):
    block = preference_block(preferences)
    if not block:
        return system
    return system.rstrip() + "\n\n" + block
