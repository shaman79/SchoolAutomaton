"""Rate limits + guessing throttles (security review): generation limits keyed per learner with a
per-IP ceiling, profile-creation cap, settings size caps, and the resume-code brute-force throttle.

Every in-process request comes from the same client IP — exactly the "whole classroom behind one
school NAT" situation the per-learner keying is for."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import RequestContext
from app.core.config import settings
from app.core.throttle import ResumeCodeGuard
from app.sanitization import ratelimit
from tests.test_progress_resume import _new_profile, _seed_lesson

API = "/api/v1"


# --------------------------------------------------------------------------- generation limits
async def test_generation_limit_is_per_learner_not_shared_by_a_school_ip(client):
    """Before: every limit was keyed on the IP, so one class shared 20/min + 300/day."""
    h1, pid1 = await _new_profile(client)
    h2, _ = await _new_profile(client)
    lesson_id, _ = await _seed_lesson("rl-lesson", pid1, ready=4, total=4)
    url = f"{API}/lessons/{lesson_id}/sections/0/generate"  # a ready section: no model call

    codes = [(await client.post(url, headers=h1)).status_code for _ in range(settings.rate_per_min)]
    assert set(codes) == {200}
    over = await client.post(url, headers=h1)
    assert over.status_code == 429
    assert int(over.headers["Retry-After"]) >= 1
    # A classmate on the same IP still has their own allowance.
    assert (await client.post(url, headers=h2)).status_code == 200


def _ctx(profile_id: int | None, ip: str = "school-nat") -> RequestContext:
    return RequestContext(ip_hash=ip, user_agent="", profile_id=profile_id)


def test_ip_ceiling_stops_code_rotation():
    lim = ratelimit.TokenBucketLimiter(per_min=2, per_day=1000, ip_multiplier=2)  # ceiling 4/min
    lim.check(_ctx(1))
    lim.check(_ctx(1))
    with pytest.raises(HTTPException) as exc:
        lim.check(_ctx(1))  # learner 1 used their own 2/min
    assert exc.value.status_code == 429 and exc.value.headers["Retry-After"]
    lim.check(_ctx(2))
    lim.check(_ctx(2))
    with pytest.raises(HTTPException) as exc:
        lim.check(_ctx(3))  # a fresh code, but the IP ceiling (2 × 2) is spent
    assert exc.value.status_code == 429
    lim.check(_ctx(3, ip="other-school"))  # another network is unaffected


def test_anonymous_requests_are_keyed_on_ip():
    lim = ratelimit.TokenBucketLimiter(per_min=2, per_day=1000, ip_multiplier=10)
    lim.check(_ctx(None))
    lim.check(_ctx(None))
    with pytest.raises(HTTPException):
        lim.check(_ctx(None))
    lim.check(_ctx(7))  # a learner with a code on the same IP has their own bucket


def test_a_refused_request_consumes_nothing():
    lim = ratelimit.TokenBucketLimiter(per_min=1, per_day=1000, ip_multiplier=1)
    lim.check(_ctx(1))
    for _ in range(3):
        with pytest.raises(HTTPException):
            lim.check(_ctx(1))
    # Learner 2 shares the (1/min) IP ceiling, which learner 1's refused calls must not have drained
    # further — it is simply spent by learner 1's single success.
    with pytest.raises(HTTPException):
        lim.check(_ctx(2))


# --------------------------------------------------------------------------- profile creation
async def test_a_class_can_create_profiles_at_once_but_minting_is_capped(client, monkeypatch):
    monkeypatch.setattr(settings, "profile_create_per_hour", 36)
    for _ in range(36):  # a class of ~35 starting together
        assert (await client.post(f"{API}/profiles", json={})).status_code == 201
    r = await client.post(f"{API}/profiles", json={})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


async def test_default_profile_creation_cap_is_sixty_per_hour():
    assert settings.profile_create_per_hour == 60


# --------------------------------------------------------------------------- settings size caps
@pytest.mark.parametrize(
    "patch",
    [
        {"theme": "x" * 500_000},
        {"font": "x" * 21},
        {"locale": "x" * 500},
        {"education_locale": "x" * 500},
        {"font_scale": 1e308},
        {"font_scale": -1},
        {"interleave_strength": -5},
        {"rest_days_per_week": 10**9},
        {"rest_days_per_week": -1},
    ],
)
async def test_unbounded_settings_are_rejected(client, patch):
    headers, _ = await _new_profile(client)
    r = await client.patch(f"{API}/profiles/me/settings", headers=headers, json=patch)
    assert r.status_code == 422, r.text[:200]


async def test_normal_settings_still_save(client):
    headers, _ = await _new_profile(client)
    body = {"theme": "highcontrast", "font": "opendyslexic", "font_scale": 1.3, "locale": "cs",
            "education_locale": "cs-CZ", "interleave_strength": 0.3, "rest_days_per_week": 1}
    r = await client.patch(f"{API}/profiles/me/settings", headers=headers, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["font_scale"] == 1.3


async def test_oversized_create_and_resume_fields_are_rejected(client):
    assert (await client.post(f"{API}/profiles", json={"locale": "x" * 100})).status_code == 422
    r = await client.post(f"{API}/profiles/resume", json={"resume_code": "A" * 1000})
    assert r.status_code == 422


# --------------------------------------------------------------------------- resume-code guessing
async def test_resume_code_guessing_is_throttled_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "resume_fail_limit", 10)
    headers, _ = await _new_profile(client)  # a learner who already signed in from this network

    for i in range(10):
        r = await client.get(f"{API}/profiles/me", headers={"X-Resume-Code": f"AAAA-{i:04d}"})
        assert r.status_code == 401
    # The next NEW unknown code is refused without being looked up (no valid/invalid oracle)...
    r = await client.get(f"{API}/profiles/me", headers={"X-Resume-Code": "AAAA-9999"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    r = await client.post(f"{API}/profiles/resume", json={"resume_code": "BBBB-0000"})
    assert r.status_code == 429
    # ...on the optional-code paths too.
    r = await client.post(f"{API}/requests", json={"prompt": "x"}, headers={"X-Resume-Code": "CCCC-0000"})
    assert r.status_code == 429
    # A code already proven valid from this network is never slowed.
    assert (await client.get(f"{API}/profiles/me", headers=headers)).status_code == 200
    r = await client.post(f"{API}/profiles/resume", json={"resume_code": headers["X-Resume-Code"]})
    assert r.status_code == 200
    # Re-sending a code already known to be wrong reveals nothing new: still a plain 401.
    r = await client.get(f"{API}/profiles/me", headers={"X-Resume-Code": "AAAA-0003"})
    assert r.status_code == 401


async def test_a_stale_code_resent_on_every_request_counts_once(client, monkeypatch):
    monkeypatch.setattr(settings, "resume_fail_limit", 3)
    for _ in range(50):  # a device holding an outdated code
        r = await client.get(f"{API}/profiles/me", headers={"X-Resume-Code": "STAL-E000"})
        assert r.status_code == 401
    # The class's own codes are unaffected.
    headers, _ = await _new_profile(client)
    assert (await client.get(f"{API}/profiles/me", headers=headers)).status_code == 200


def test_resume_guard_window_expires():
    now = [1000.0]
    guard = ResumeCodeGuard(limit=lambda: 2, window_s=lambda: 600.0, clock=lambda: now[0])
    for code in ("a", "b"):
        guard.before_lookup("ip", code)
        guard.after_lookup("ip", code, found=False)
    with pytest.raises(HTTPException) as exc:
        guard.before_lookup("ip", "c")
    assert exc.value.status_code == 429
    assert 590 <= int(exc.value.headers["Retry-After"]) <= 601
    guard.before_lookup("other-ip", "c")  # per IP
    now[0] += 601
    guard.before_lookup("ip", "c")  # the window slid past both failures
