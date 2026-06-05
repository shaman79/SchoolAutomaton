"""Layer 0 — in-memory per-(ip_hash) token bucket (SPEC §5). Anonymous resume codes are trivial to
rotate, so we key on the salted ``ip_hash`` from ``RequestContext`` (not the profile).

Two independent buckets per key — per-minute (``settings.rate_per_min``) and per-day
(``settings.rate_per_day``) — both must have a token. ``check(ctx)`` raises ``HTTPException 429`` when
either is exhausted. Also exposed as a FastAPI dependency (``rate_limit_dependency``) and an injection
strike counter for the audit/abuse signal.

NOTE (wiring): the ``POST /requests`` route is a frozen spine file and is NOT edited by this module.
To enforce the limit, the route (or its dependencies) should call ``check(ctx)`` /
``rate_limit_dependency`` before ``sanitize_request``. ``sanitize_request`` also calls ``check(ctx)``
itself, so the limit is enforced regardless. See the structured report notes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status

from ..api.deps import RequestContext, get_request_context
from ..core.config import settings


@dataclass
class _Bucket:
    """A classic token bucket. ``capacity`` tokens refill linearly at ``refill_per_sec``."""

    capacity: float
    refill_per_sec: float
    tokens: float = field(default=0.0)
    updated_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def _refill(self, now: float) -> None:
        elapsed = now - self.updated_at
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            self.updated_at = now

    def try_consume(self, amount: float = 1.0) -> bool:
        now = time.monotonic()
        self._refill(now)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False

    def retry_after_sec(self, amount: float = 1.0) -> int:
        deficit = max(0.0, amount - self.tokens)
        if self.refill_per_sec <= 0:
            return 60
        return max(1, int(deficit / self.refill_per_sec) + 1)


class TokenBucketLimiter:
    """Thread-safe, in-memory two-tier (per-minute + per-day) limiter keyed on ip_hash."""

    def __init__(self, per_min: int, per_day: int) -> None:
        self.per_min = max(1, per_min)
        self.per_day = max(1, per_day)
        self._minute: dict[str, _Bucket] = {}
        self._day: dict[str, _Bucket] = {}
        self._strikes: dict[str, int] = {}
        self._lock = threading.Lock()

    def _buckets_for(self, key: str) -> tuple[_Bucket, _Bucket]:
        minute = self._minute.get(key)
        if minute is None:
            minute = _Bucket(capacity=float(self.per_min), refill_per_sec=self.per_min / 60.0)
            self._minute[key] = minute
        day = self._day.get(key)
        if day is None:
            day = _Bucket(capacity=float(self.per_day), refill_per_sec=self.per_day / 86_400.0)
            self._day[key] = day
        return minute, day

    def check(self, ctx: RequestContext) -> None:
        """Consume one token from both tiers; raise HTTP 429 if either is exhausted."""
        key = ctx.ip_hash or "unknown"
        with self._lock:
            minute, day = self._buckets_for(key)
            # Peek-then-consume atomically: only consume the minute token if the day token is available.
            day_now = time.monotonic()
            day._refill(day_now)
            if day.tokens < 1.0:
                retry = day.retry_after_sec()
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily request limit reached. Please come back tomorrow.",
                    headers={"Retry-After": str(retry)},
                )
            if not minute.try_consume(1.0):
                retry = minute.retry_after_sec()
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="You're going a bit fast. Please wait a moment and try again.",
                    headers={"Retry-After": str(retry)},
                )
            day.tokens -= 1.0

    def record_strike(self, ctx: RequestContext, amount: int = 1) -> int:
        """Increment the injection-strike counter for abuse tracking; returns the new total."""
        key = ctx.ip_hash or "unknown"
        with self._lock:
            self._strikes[key] = self._strikes.get(key, 0) + amount
            return self._strikes[key]

    def strikes(self, ctx: RequestContext) -> int:
        return self._strikes.get(ctx.ip_hash or "unknown", 0)

    def reset(self) -> None:
        """Clear all state (used by tests)."""
        with self._lock:
            self._minute.clear()
            self._day.clear()
            self._strikes.clear()


# Module-level singleton, sized from settings at import.
limiter = TokenBucketLimiter(settings.rate_per_min, settings.rate_per_day)


def check(ctx: RequestContext) -> None:
    """Convenience wrapper around the module limiter (raises HTTP 429 when exceeded)."""
    limiter.check(ctx)


async def rate_limit_dependency(
    ctx: RequestContext = Depends(get_request_context),
) -> RequestContext:
    """FastAPI dependency that enforces the limit and returns the context for downstream use."""
    limiter.check(ctx)
    return ctx
