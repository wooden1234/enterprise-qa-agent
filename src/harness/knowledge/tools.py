"""检索和片段读取工具。"""

from __future__ import annotations

from src.harness.knowledge.index import SectionIndex
from src.harness.tools.runtime import ToolDefinition, ToolRuntime


def knowledge_runtime(index=None, fail_tool=""):
    index = index or SectionIndex.load()

    def search(arguments):
        if fail_tool == "search_documents":
            return {
                "ok": False,
                "tool": "search_documents",
                "arguments": arguments,
                "error": "simulated search_documents failure",
            }
        query = str(arguments.get("query") or "")
        from src.retrieval.retriever import search_policy

        return search_policy(query, arguments=arguments)

    def read(arguments):
        if fail_tool == "read_document":
            return {
                "ok": False,
                "tool": "read_document",
                "arguments": arguments,
                "error": "simulated read_document failure",
            }
        section_id = str(arguments.get("section_id") or "")
        return index.read(section_id, arguments)

    return ToolRuntime(
        (
            ToolDefinition("search_documents", search, "检索制度章节，不返回正文"),
            ToolDefinition("read_document", read, "按 section_id 读取章节原文"),
        )
    )


def planner_runtime(model, fail_tool=""):
    """主代理只有一个业务工具：把制度问题交给检索子代理。"""
    knowledge = knowledge_runtime(fail_tool=fail_tool)

    def consult(arguments):
        query = str(arguments.get("query") or arguments.get("question") or "")
        from src.retrieval.agent import RetrievalAgent
        from src.retrieval.script import RetrievalScript

        worker = model if getattr(model, "mode", "") == "live_model" else RetrievalScript()
        return RetrievalAgent(knowledge, worker).run(query, arguments)

    return ToolRuntime((ToolDefinition("consult_retrieval", consult, "把制度问题交给检索子代理"),))
