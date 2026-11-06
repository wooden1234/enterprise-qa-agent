"""内存事件日志。产品版 harness 把同一份日志落在 PostgreSQL。"""

from __future__ import annotations

from src.harness.session.types import EventDraft, SessionEvent, new_id, utcnow


class MemorySessionStore:
    def __init__(self):
        self._events = []

    def append(self, draft):
        if not isinstance(draft, EventDraft):
            raise TypeError("append expects EventDraft")
        event = SessionEvent(
            seq=len(self._events) + 1,
            event_id=new_id(),
            event_type=draft.event_type,
            run_id=draft.run_id,
            turn=draft.turn,
            step=draft.step,
            data=dict(draft.data),
            created_at=utcnow(),
        )
        self._events.append(event)
        return event

    def load_events(self):
        return list(self._events)
