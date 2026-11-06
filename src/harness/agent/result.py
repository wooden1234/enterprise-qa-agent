"""一轮循环的结果。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunResult:
    session_id: str
    run_id: str
    finish_reason: str
    status: str
    answer: str = ""
    citations: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    confirmation_needed: str = ""
    events: list = field(default_factory=list)
    error: str = ""
