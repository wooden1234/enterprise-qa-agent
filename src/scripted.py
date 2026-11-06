"""离线脚本策略。只验证循环能走通，不证明真实模型的选择。"""

from __future__ import annotations

import json

from src.tools import content_terms


_CHAT = ("你好", "您好", "嗨", "你好呀", "早上好", "晚上好", "在吗", "谢谢", "再见", "hello", "hi")


class ScriptedModel:
    mode = "scripted_mock"
    model_name = "scripted-policy"

    def __init__(self):
        self.question = ""
        self.query = ""
        self.consulted = None
        self.tool_retries = 0

    def complete(self, messages):
        self.question = _question(messages) or self.question
        observation = _last_observation(messages)
        action = self._decide(observation)
        return json.dumps(action, ensure_ascii=False), action

    def _decide(self, observation):
        if observation and observation.get("type") == "review":
            if self.consulted and not self.consulted.get("ok"):
                return self._tool_error(self.consulted, "审核未通过，工具失败不能改成已完成")
            action = self._summarize(self.consulted)
            action["decision_basis"] = "审核未通过，按审核意见重新作答"
            return action
        if _is_chat(self.question) and not observation:
            return _action(
                "这是闲聊，直接回答，不查制度",
                "submit_answer",
                _payload(
                    "completed",
                    "你好，我是企业知识问答助手。需要查制度时直接问我，例如年假、报销或设备申领。",
                    [],
                    answer_kind="chat",
                ),
            )
        if observation and observation.get("tool") == "consult_retrieval":
            self.consulted = observation
            if not observation.get("ok"):
                if self.tool_retries < 1:
                    self.tool_retries += 1
                    return _action(
                        "检索子代理返回工具失败，由主代理重试一次",
                        "consult_retrieval",
                        {"query": self.query},
                    )
                return self._tool_error(observation, "重试后仍然失败，结束并返回工具失败")
            return self._summarize(observation)
        self.query = " ".join(content_terms(self.question)) or self.question
        self.tool_retries = 0
        return _action("这是制度问题，交给检索子代理", "consult_retrieval", {"query": self.query})

    def _tool_error(self, observation, basis):
        return _action(
            basis,
            "submit_answer",
            _payload(
                "tool_error",
                "工具调用失败，没有取得可用制度原文。",
                [],
                [observation.get("error") or "工具失败"],
            ),
        )

    def _summarize(self, observation):
        findings = (observation or {}).get("findings") or []
        status = (observation or {}).get("status")
        annual = [item for item in findings if "不满 10 年的，年休假" in item.get("quote", "")]
        claims = [item for item in findings if "报销期限为" in item.get("quote", "")]
        conflict_items = claims if len({item.get("quote") for item in claims}) >= 2 else annual
        if status == "needs_confirmation" or len({item.get("quote") for item in conflict_items}) >= 2:
            cited = conflict_items or findings
            citations = [{"doc_id": item["doc_id"], "quote": item["quote"]} for item in cited]
            answer = "；".join(
                "%s（%s）写明“%s”" % (item["doc_id"], item["version_date"], item["quote"]) for item in cited
            )
            answer += "。两版都没有写明优先级，请确认适用哪一版。"
            fallback = "请确认应适用哪一条报销期限。" if claims else "请确认应适用哪一版假期管理制度。"
            return _action(
                "检索结果有版本冲突，总结为请求确认",
                "submit_answer",
                _payload(
                    "needs_confirmation",
                    answer,
                    citations,
                    ["缺少版本优先级"],
                    observation.get("confirmation_needed") or fallback,
                ),
            )
        if findings and status == "ready":
            item = findings[0]
            return _action(
                "检索子代理已读到原文，按片段总结",
                "submit_answer",
                _payload(
                    "completed",
                    "%s《%s》：%s" % (item["doc_id"], item["title"], item["quote"]),
                    [{"doc_id": item["doc_id"], "quote": item["quote"]}],
                ),
            )
        return _action(
            "检索子代理没有找到可用原文",
            "submit_answer",
            _payload(
                "insufficient_evidence",
                "现有制度里没有这个问题的依据。",
                [],
                observation.get("gaps") if observation else ["没有命中相关制度"],
            ),
        )


def _question(messages):
    for message in reversed(messages):
        content = str(message.get("content") or "")
        if message.get("role") == "user" and content.startswith("当前问题："):
            return content.split("：", 1)[1]
    return ""


def _last_observation(messages):
    if not messages:
        return None
    content = str(messages[-1].get("content") or "")
    if messages[-1].get("role") != "user" or not content.startswith("工具结果："):
        return None
    return json.loads(content.split("\n", 1)[1])


def _action(basis, name, arguments):
    return {"decision_basis": basis, "action": name, "arguments": arguments}


def _is_chat(question):
    text = str(question or "").strip().lower().rstrip("!！?？。.~ ")
    return text in _CHAT


def _payload(status, answer, citations, gaps=None, confirmation="", answer_kind="policy"):
    return {
        "status": status,
        "answer": answer,
        "citations": citations,
        "gaps": gaps or [],
        "confirmation_needed": confirmation,
        "answer_kind": answer_kind,
    }
