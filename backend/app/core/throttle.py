"""In-memory throttles for credential guessing: learner resume codes and the admin login.

Both are per-process (like the rate limiter) and keyed on the salted client-IP hash — never the raw IP.

* :class:`ResumeCodeGuard` — resume codes are ~40 bits, so an unthrottled lookup endpoint can be
  enumerated. We count the DISTINCT unknown codes each IP tries inside a sliding window; past the
  limit, NEW codes from that IP get 429 without being looked up (looking them up would hand the
  attacker a valid/invalid oracle). Codes this IP has already proven valid keep working, and the same
  stale code re-sent on every request counts once — so a classroom behind one school NAT, or a
  device holding an outdated code, never locks anyone out by itself.
* :class:`LoginThrottle` — admin login: failures per minute per key (IP and username), then an
  escalating lockout (1 min, 2, 4, 8, capped at 15). An attempt is counted when it STARTS (and
  forgiven on success), so a burst of parallel guesses can't all slip past before the first fails.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable

from fastapi import HTTPException, status


def _too_many(retry_after: float, detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(1, int(retry_after) + 1))},
    )


class ResumeCodeGuard:
    """Per-IP throttle on failed resume-code lookups (see module docstring)."""

    # Remember a code that worked from an IP for this long (a school day and then some).
    KNOWN_TTL_S = 18 * 3600.0
    MAX_KNOWN_PER_IP = 2000
    _SWEEP_EVERY = 1024

    def __init__(
        self,
        limit: Callable[[], int],
        window_s: Callable[[], float],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._fails: dict[str, dict[str, float]] = {}  # ip -> {code_hash: first failure time}
        self._known: dict[str, dict[str, float]] = {}  # ip -> {code_hash: last success time}
        self._lock = threading.Lock()
        self._ops = 0

    def _live_fails(self, ip: str, now: float) -> dict[str, float]:
        fails = self._fails.get(ip)
        if not fails:
            return {}
        horizon = now - self._window()
        for code, ts in list(fails.items()):
            if ts < horizon:
                del fails[code]
        if not fails:
            self._fails.pop(ip, None)
        return fails

    def before_lookup(self, ip: str, code_hash: str) -> None:
        """Raise 429 if ``ip`` is over its budget of distinct unknown codes and ``code_hash`` is new."""
        with self._lock:
            now = self._clock()
            known = self._known.get(ip)
            if known and now - known.get(code_hash, -1e18) <= self.KNOWN_TTL_S:
                return  # proven valid from this IP — never throttled
            fails = self._live_fails(ip, now)
            if code_hash in fails:
                return  # a repeat of a code already known to be wrong reveals nothing new
            if len(fails) >= max(1, self._limit()):
                retry = min(fails.values()) + self._window() - now
                raise _too_many(
                    retry, "Too many unknown resume codes from this network. Please wait a bit."
                )

    def after_lookup(self, ip: str, code_hash: str, *, found: bool) -> None:
        with self._lock:
            now = self._clock()
            if found:
                known = self._known.setdefault(ip, {})
                known[code_hash] = now
                if len(known) > self.MAX_KNOWN_PER_IP:
                    oldest = min(known, key=known.__getitem__)
                    del known[oldest]
            else:
                self._fails.setdefault(ip, {}).setdefault(code_hash, now)
            self._ops += 1
            if self._ops % self._SWEEP_EVERY == 0:
                self._sweep(now)

    def _sweep(self, now: float) -> None:
        for ip in list(self._fails):
            self._live_fails(ip, now)
        for ip, known in list(self._known.items()):
            for code, ts in list(known.items()):
                if now - ts > self.KNOWN_TTL_S:
                    del known[code]
            if not known:
                del self._known[ip]

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()
            self._known.clear()
            self._ops = 0


class LoginThrottle:
    """Failures-per-minute per key, then an escalating lockout (see module docstring)."""

    WINDOW_S = 60.0
    BASE_LOCK_S = 60.0
    MAX_LOCK_S = 900.0

    def __init__(self, limit: Callable[[], int], clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lockouts: dict[str, int] = {}
        self._lock = threading.Lock()

    def begin(self, keys: Iterable[str]) -> None:
        """Called before verifying a password: 429 while any key is locked; otherwise count this
        attempt (pessimistically, as a failure) and lock the key once it reaches the limit."""
        keys = list(keys)
        with self._lock:
            now = self._clock()
            waits = [self._locked_until.get(k, 0.0) - now for k in keys]
            if max(waits, default=0.0) > 0:
                raise _too_many(max(waits), "Too many login attempts. Please try again later.")
            limit = max(1, self._limit())
            for k in keys:
                attempts = self._attempts.setdefault(k, deque())
                while attempts and attempts[0] <= now - self.WINDOW_S:
                    attempts.popleft()
                attempts.append(now)
                if len(attempts) >= limit:
                    n = self._lockouts.get(k, 0)
                    self._locked_until[k] = now + min(self.MAX_LOCK_S, self.BASE_LOCK_S * (2**n))
                    self._lockouts[k] = n + 1
                    attempts.clear()

    def succeeded(self, keys: Iterable[str]) -> None:
        """A correct password: forgive this attempt and clear the keys' history."""
        with self._lock:
            for k in keys:
                self._attempts.pop(k, None)
                self._locked_until.pop(k, None)
                self._lockouts.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._locked_until.clear()
            self._lockouts.clear()


def _settings():
    from .config import settings  # noqa: PLC0415 — read live so a settings change applies

    return settings


resume_guard = ResumeCodeGuard(
    limit=lambda: _settings().resume_fail_limit,
    window_s=lambda: float(_settings().resume_fail_window_s),
)
admin_login_throttle = LoginThrottle(limit=lambda: _settings().admin_login_fail_limit)


def reset_all() -> None:
    """Clear every throttle in this module (tests)."""
    resume_guard.reset()
    admin_login_throttle.reset()
