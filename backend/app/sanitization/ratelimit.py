"""Layer 0 — in-memory token-bucket rate limits (SPEC §5).

**Generation** (``check(ctx)`` / ``rate_limit_dependency`` — prompts, generation starts, section fills):
two buckets, per-minute (``settings.rate_per_min``) and per-day (``settings.rate_per_day``), keyed on
the LEARNER when the request carries a valid resume code (``ctx.profile_id``) and on the salted
``ip_hash`` otherwise. A school behind one NAT therefore no longer shares one 20/min + 300/day
allowance between every child in the building. Anonymous resume codes are cheap to mint, so every IP
also has a ceiling of ``settings.rate_ip_multiplier`` × those limits that ALL its traffic (any code,
or none) draws from: rotating codes can't lift one machine past it.

**Answers** (``check_answer_rate`` / ``check_llm_grading_rate``): per learner per minute, with a tighter
limit (and a per-IP ceiling) for answers graded by the AI, each of which is a paid model call.

**Profile creation** (``check_profile_create``): per IP per hour.

Every limit raises ``HTTPException 429`` with a ``Retry-After`` header. ``record_strike`` keeps the
injection strike counter (audit/abuse signal).

NOTE (wiring): ``sanitize_request`` calls ``check(ctx)`` itself, and the generation routes depend on
``rate_limit_dependency``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status

from ..api.deps import RequestContext, get_request_context
from ..core.config import settings

_DAY_MSG = "Daily request limit reached. Please come back tomorrow."
_MIN_MSG = "You're going a bit fast. Please wait a moment and try again."


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


@dataclass(frozen=True)
class Limit:
    """One bucket to draw a token from: ``capacity`` requests per ``period_s`` for ``key``."""

    key: str
    capacity: int
    period_s: float
    message: str = _MIN_MSG


class KeyedRateLimiter:
    """Thread-safe token buckets keyed by arbitrary strings.

    ``hit(limits)`` is all-or-nothing: it consumes one token from EVERY listed bucket only when all
    of them have one, otherwise raises 429 (with the longest ``Retry-After`` among the empty ones) and
    consumes nothing. Idle (refilled) buckets are pruned periodically so memory stays bounded."""

    _PRUNE_EVERY = 4096

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, int, float], _Bucket] = {}
        self._lock = threading.Lock()
        self._hits = 0

    def _get(self, lim: Limit) -> _Bucket:
        capacity = max(1, int(lim.capacity))
        key = (lim.key, capacity, float(lim.period_s))
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(capacity=float(capacity), refill_per_sec=capacity / float(lim.period_s))
            self._buckets[key] = bucket
        return bucket

    def hit(self, limits: Sequence[Limit]) -> None:
        with self._lock:
            now = time.monotonic()
            pairs = [(lim, self._get(lim)) for lim in limits]
            for _lim, bucket in pairs:
                bucket._refill(now)
            empty = [(lim, b) for lim, b in pairs if b.tokens < 1.0]
            if empty:
                lim, bucket = max(empty, key=lambda p: p[1].retry_after_sec())
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=lim.message,
                    headers={"Retry-After": str(bucket.retry_after_sec())},
                )
            for _lim, bucket in pairs:
                bucket.tokens -= 1.0
            self._hits += 1
            if self._hits % self._PRUNE_EVERY == 0:
                self._prune(now)

    def _prune(self, now: float) -> None:
        for key, bucket in list(self._buckets.items()):
            bucket._refill(now)
            if bucket.tokens >= bucket.capacity:
                del self._buckets[key]

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._hits = 0


class TokenBucketLimiter:
    """The generation limiter: per-minute + per-day buckets per learner (else per IP), plus a per-IP
    ceiling of ``ip_multiplier`` × both. See the module docstring."""

    def __init__(self, per_min: int, per_day: int, ip_multiplier: int | None = None) -> None:
        self.per_min = max(1, per_min)
        self.per_day = max(1, per_day)
        self.ip_multiplier = max(
            1, ip_multiplier if ip_multiplier is not None else settings.rate_ip_multiplier
        )
        self._buckets = KeyedRateLimiter()
        self._strikes: dict[str, int] = {}
        self._lock = threading.Lock()

    def limits_for(self, ctx: RequestContext) -> list[Limit]:
        ip = ctx.ip_hash or "unknown"
        who = f"p:{ctx.profile_id}" if ctx.profile_id is not None else f"a:{ip}"
        mult = self.ip_multiplier
        return [
            Limit(f"gen-day:{who}", self.per_day, 86_400.0, _DAY_MSG),
            Limit(f"gen-min:{who}", self.per_min, 60.0, _MIN_MSG),
            Limit(f"gen-day:ip:{ip}", self.per_day * mult, 86_400.0, _DAY_MSG),
            Limit(f"gen-min:ip:{ip}", self.per_min * mult, 60.0, _MIN_MSG),
        ]

    def check(self, ctx: RequestContext) -> None:
        """Consume one token from every tier; raise HTTP 429 (+ Retry-After) if any is exhausted."""
        self._buckets.hit(self.limits_for(ctx))

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
        self._buckets.reset()
        with self._lock:
            self._strikes.clear()


# Module-level singletons, sized from settings at import.
limiter = TokenBucketLimiter(settings.rate_per_min, settings.rate_per_day)
# Answers + profile creation (sized from settings at call time, so a settings change applies).
aux_limiter = KeyedRateLimiter()


def check(ctx: RequestContext) -> None:
    """Convenience wrapper around the module limiter (raises HTTP 429 when exceeded)."""
    limiter.check(ctx)


async def rate_limit_dependency(
    ctx: RequestContext = Depends(get_request_context),
) -> RequestContext:
    """FastAPI dependency that enforces the limit and returns the context for downstream use."""
    limiter.check(ctx)
    return ctx


def check_answer_rate(profile_id: int) -> None:
    """Every answer submission (POST /answers, POST /review/{id}): per learner per minute."""
    aux_limiter.hit([Limit(f"ans:p:{profile_id}", settings.answer_rate_per_min, 60.0)])


def check_llm_grading_rate(profile_id: int, ip_hash: str | None) -> None:
    """An answer about to be graded by the AI: a tighter per-learner limit, plus a per-IP ceiling
    (``rate_ip_multiplier`` ×) so a pile of fresh profiles on one machine can't multiply it."""
    per_min = settings.answer_llm_rate_per_min
    mult = max(1, settings.rate_ip_multiplier)
    aux_limiter.hit(
        [
            Limit(f"ans-llm:p:{profile_id}", per_min, 60.0),
            Limit(f"ans-llm:ip:{ip_hash or 'unknown'}", per_min * mult, 60.0),
        ]
    )


def check_profile_create(ip_hash: str | None) -> None:
    """POST /profiles: new anonymous profiles per client IP per hour."""
    aux_limiter.hit(
        [
            Limit(
                f"profile-create:ip:{ip_hash or 'unknown'}",
                settings.profile_create_per_hour,
                3600.0,
                "Too many new profiles from this network. Please try again later.",
            )
        ]
    )


def reset_all() -> None:
    """Clear every limiter in this module (tests)."""
    limiter.reset()
    aux_limiter.reset()
