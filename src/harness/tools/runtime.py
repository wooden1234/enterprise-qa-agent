"""工具菜单。模型只能调用这里登记的名称。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolDefinition:
    name: str
    handler: object
    description: str = ""


class ToolRuntime:
    def __init__(self, definitions):
        self._definitions = tuple(definitions)
        self._by_name = {item.name: item for item in self._definitions}

    def resolve(self, name):
        return self._by_name.get(name)

    def names(self):
        return list(self._by_name)
