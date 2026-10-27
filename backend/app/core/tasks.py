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
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

# A finished channel is kept this long for late subscribers, then dropped (the stream endpoint falls
# back to the request row's status) so the registry doesn't grow with every lesson ever made.
_DONE_CHANNEL_TTL_S = 600.0


@dataclass
class _TaskChannel:
    backlog: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    done: bool = False


class TaskRegistry:
    """Process-wide singleton broker for generation progress events."""

    def __init__(self) -> None:
        # No lock: nothing below awaits inside a read-modify-write, so on the one event loop each
        # update is already atomic (an asyncio.Lock here also tied the singleton to the first loop
        # that contended for it, which broke under a test runner's fresh loop per test).
        self._channels: dict[str, _TaskChannel] = {}
        # Work a restart would lose (whole generations, on-demand sections); the deploy script waits
        # for this to reach 0 before restarting the backend (GET /api/v1/health).
        self._active: dict[str, int] = {}

    @contextlib.contextmanager
    def working(self, key: str) -> Iterator[None]:
        """Count ``key`` as in-flight work for the duration of the block."""
        self._active[key] = self._active.get(key, 0) + 1
        try:
            yield
        finally:
            left = self._active.get(key, 1) - 1
            if left > 0:
                self._active[key] = left
            else:
                self._active.pop(key, None)

    def is_working(self, key: str) -> bool:
        return key in self._active

    def active_count(self) -> int:
        return sum(self._active.values())

    async def _channel(self, request_id: str) -> _TaskChannel:
        return self._channels.setdefault(request_id, _TaskChannel())

    async def publish(self, request_id: str, event: str, data: dict[str, Any]) -> None:
        """Emit an SSE event ``{event, data}`` to all subscribers and append to the backlog."""
        ch = await self._channel(request_id)
        payload = {"event": event, "data": data}
        ch.backlog.append(payload)
        if event in ("ready", "failed") and not ch.done:
            ch.done = True
            with contextlib.suppress(RuntimeError):  # no running loop (sync tests): keep it
                asyncio.get_running_loop().call_later(
                    _DONE_CHANNEL_TTL_S, self._drop_if_idle, request_id, ch
                )
        for q in list(ch.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    def _drop_if_idle(self, request_id: str, ch: _TaskChannel) -> None:
        if self._channels.get(request_id) is ch and not ch.subscribers:
            del self._channels[request_id]

    async def restart(self, request_id: str) -> None:
        """Start a fresh event history for a (re)started generation: a retry after a failure must not
        replay the old 'failed' to whoever subscribes next. Current subscribers stay attached."""
        old = self._channels.get(request_id)
        self._channels[request_id] = _TaskChannel(subscribers=old.subscribers if old else set())

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
        self._channels.pop(request_id, None)


# Process-wide singleton.
task_registry = TaskRegistry()
