import asyncio
import json
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    """In-memory conversations with a TTL and an LRU cap. Lost on restart, which is fine for a demo."""

    def __init__(self, ttl_seconds: float, max_sessions: int):
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def get_or_create(self, session_id: str | None) -> Session:
        self._evict()
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            self._sessions.move_to_end(session_id)
        else:
            session = Session(session_id or uuid.uuid4().hex)
            self._sessions[session.id] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        session.updated_at = time.monotonic()
        return session

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def __len__(self) -> int:
        return len(self._sessions)

    def _evict(self) -> None:
        cutoff = time.monotonic() - self.ttl
        for sid in [sid for sid, s in self._sessions.items() if s.updated_at < cutoff and not s.lock.locked()]:
            del self._sessions[sid]


def trim_history(messages: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """Drop the oldest whole turns until the history fits.

    A turn starts at a user message, so an assistant message with tool_calls is never separated
    from its tool results (the API rejects a history where that happens). The latest turn is
    always kept, even when it alone is over the budget.
    """
    starts = [i for i, m in enumerate(messages) if m["role"] == "user"]
    if not starts:
        return messages
    sizes = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(messages)
        sizes.append(sum(len(json.dumps(m, ensure_ascii=False)) for m in messages[start:end]))
    total = sum(sizes)
    first = 0
    while first < len(starts) - 1 and total > max_chars:
        total -= sizes[first]
        first += 1
    return messages[starts[first]:]

def backup_table(data=None):
    if data is None:
        return None
    return data

def backup_table(data=None):
    if data is None:
        return None
    return data

def compress_payload(data=None):
    if data is None:
        return None
    return data