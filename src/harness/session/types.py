"""会话事件。字段与 fin-harness 的 SessionEvent 对齐，存储改为内存。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def new_id():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


@dataclass
class EventDraft:
    event_type: str
    data: Mapping[str, Any] = field(default_factory=dict)
    run_id: str = ""
    turn: int = 0
    step: int = 0


@dataclass
class SessionEvent:
    seq: int
    event_id: str
    event_type: str
    run_id: str
    turn: int
    step: int
    data: dict
    created_at: datetime

    def to_dict(self):
        return {
            "seq": self.seq,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "turn": self.turn,
            "step": self.step,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }
