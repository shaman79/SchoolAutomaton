"""Admin login hardening (security review): Argon2 runs off the event loop, unknown usernames cost
the same as real ones (no timing oracle), and failures are throttled per IP and per username with an
escalating lockout."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

from app.core import security
from app.core.config import settings
from app.core.throttle import LoginThrottle

API = "/api/v1"
LOGIN = f"{API}/admin/auth/login"
GOOD = {"username": "admin", "password": "admin12345"}  # tests/conftest.py bootstrap admin


async def test_unknown_username_is_verified_against_a_dummy_hash_off_the_loop(client, monkeypatch):
    calls = []
    real = security.verify_password

    def spy(password, password_hash):
        calls.append((password_hash, threading.get_ident()))
        return real(password, password_hash)

    monkeypatch.setattr(security, "verify_password", spy)
    loop_thread = threading.get_ident()
    assert (await client.post(LOGIN, json={"username": "nobody", "password": "x"})).status_code == 401
    assert (await client.post(LOGIN, json={"username": "admin", "password": "x"})).status_code == 401
    assert len(calls) == 2  # an unknown user still pays for one Argon2 verification
    dummy, real_user = calls[0][0], calls[1][0]
    assert dummy.startswith("$argon2") and dummy != real_user
    assert all(tid != loop_thread for _, tid in calls)  # never on the event loop


async def test_failed_logins_do_not_stall_the_event_loop(client, monkeypatch):
    """The reviewer's PoC: 20 concurrent bad logins used to freeze the loop for seconds."""
    monkeypatch.setattr(settings, "admin_login_fail_limit", 1000)  # let them all reach Argon2
    lags: list[float] = []
    stop = False

    async def ticker():
        while not stop:
            t = time.perf_counter()
            await asyncio.sleep(0.01)
            lags.append(time.perf_counter() - t - 0.01)

    tk = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    lags.clear()
    codes = await asyncio.gather(
        *[client.post(LOGIN, json={"username": "admin", "password": f"g{i}"}) for i in range(20)]
    )
    stop = True
    await tk
    assert {r.status_code for r in codes} == {401}
    assert max(lags) < 0.1, f"event loop stalled {max(lags) * 1000:.0f} ms"


async def test_login_failures_are_throttled_and_success_resets(client):
    for i in range(4):
        assert (await client.post(LOGIN, json={"username": "admin", "password": f"bad{i}"})).status_code == 401
    assert (await client.post(LOGIN, json=GOOD)).status_code == 200  # 5th attempt, correct: resets
    for i in range(5):
        assert (await client.post(LOGIN, json={"username": "admin", "password": f"bad{i}"})).status_code == 401
    r = await client.post(LOGIN, json=GOOD)  # locked now — even the right password waits
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 61
    # The IP is locked too, whatever username it tries next.
    assert (await client.post(LOGIN, json={"username": "other", "password": "x"})).status_code == 429


async def test_locked_login_skips_argon2(client, monkeypatch):
    for i in range(5):
        await client.post(LOGIN, json={"username": "admin", "password": f"bad{i}"})
    calls = []
    monkeypatch.setattr(security, "verify_password", lambda *a: calls.append(a) or False)
    assert (await client.post(LOGIN, json=GOOD)).status_code == 429
    assert calls == []


async def test_oversized_credentials_are_422(client):
    r = await client.post(LOGIN, json={"username": "admin", "password": "x" * 100_000})
    assert r.status_code == 422


def test_lockout_escalates_and_is_capped():
    now = [0.0]
    th = LoginThrottle(limit=lambda: 5, clock=lambda: now[0])

    def fail_until_locked() -> int:
        for _ in range(5):
            th.begin(["user:admin"])
        with pytest.raises(HTTPException) as exc:
            th.begin(["user:admin"])
        return int(exc.value.headers["Retry-After"])

    waits = []
    for _ in range(6):
        waits.append(fail_until_locked())
        now[0] += waits[-1] + 1
    assert waits[0] <= 61 and waits[1] > waits[0] and waits[2] > waits[1]
    assert max(waits) <= 901  # capped at 15 minutes
    th.succeeded(["user:admin"])
    th.begin(["user:admin"])  # a success clears the history
