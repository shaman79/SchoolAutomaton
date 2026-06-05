"""In-process generation task registry + SSE event broker.

Background generation (lesson/quiz) runs as an asyncio task; the frontend ``/loading`` screen
subscribes via SSE. We keep a tiny in-memory registry keyed by ``request_id`` that fans progress
events out to any subscribers and replays the backlog to late subscribers (so a client that
connects after generation started still sees prior events). SPEC open-decision #2/#3: SSE +
in-process asyncio (no external broker in v1).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _TaskChannel:
    backlog: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    done: bool = False


class TaskRegistry:
    """Process-wide singleton broker for generation progress events."""

    def __init__(self) -> None:
        self._channels: dict[str, _TaskChannel] = {}
        self._lock = asyncio.Lock()

    async def _channel(self, request_id: str) -> _TaskChannel:
        async with self._lock:
            return self._channels.setdefault(request_id, _TaskChannel())

    async def publish(self, request_id: str, event: str, data: dict[str, Any]) -> None:
        """Emit an SSE event ``{event, data}`` to all subscribers and append to the backlog."""
        ch = await self._channel(request_id)
        payload = {"event": event, "data": data}
        ch.backlog.append(payload)
        if event in ("ready", "failed"):
            ch.done = True
        for q in list(ch.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    async def subscribe(self, request_id: str) -> tuple[asyncio.Queue[dict[str, Any]], list[dict]]:
        """Register a subscriber. Returns its queue and the current backlog to replay first."""
        ch = await self._channel(request_id)
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        ch.subscribers.add(q)
        return q, list(ch.backlog)

    async def unsubscribe(self, request_id: str, q: asyncio.Queue) -> None:
        ch = self._channels.get(request_id)
        if ch:
            ch.subscribers.discard(q)

    def is_done(self, request_id: str) -> bool:
        ch = self._channels.get(request_id)
        return bool(ch and ch.done)

    async def cleanup(self, request_id: str) -> None:
        async with self._lock:
            self._channels.pop(request_id, None)


# Process-wide singleton.
task_registry = TaskRegistry()
