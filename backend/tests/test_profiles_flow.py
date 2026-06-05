"""End-to-end profile slice over the real ASGI app (no AI needed)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_resume_me_settings(client):
    # Create
    r = await client.post("/api/v1/profiles", json={"locale": "cs", "age_band": "primary"})
    assert r.status_code == 201, r.text
    data = r.json()
    code = data["resume_code"]
    assert "-" in code and len(code) == 9  # XXXX-XXXX
    assert data["profile"]["level"] == 1
    assert data["settings"]["locale"] == "cs"

    # Resume
    r = await client.post("/api/v1/profiles/resume", json={"resume_code": code})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["gamification"]["level"] == 1
    assert env["gamification"]["streak"]["current"] == 0

    # Me (auth header)
    r = await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": code})
    assert r.status_code == 200

    # Bad code
    r = await client.get("/api/v1/profiles/me", headers={"X-Resume-Code": "ZZZZ-ZZZZ"})
    assert r.status_code == 401

    # Update settings
    r = await client.patch(
        "/api/v1/profiles/me/settings",
        headers={"X-Resume-Code": code},
        json={"reduced_motion": True, "font": "opendyslexic", "daily_goal": "serious"},
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["reduced_motion"] is True
    assert s["font"] == "opendyslexic"
    assert s["daily_goal"] == "serious"


@pytest.mark.asyncio
async def test_resume_normalization(client):
    r = await client.post("/api/v1/profiles", json={})
    code = r.json()["resume_code"]
    # lowercase + no dash should still resolve (Crockford normalization)
    r = await client.post(
        "/api/v1/profiles/resume", json={"resume_code": code.lower().replace("-", "")}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_login_and_dashboard(client):
    r = await client.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": "admin12345"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = await client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert "requests_24h" in r.json()

    # No token → 401
    assert (await client.get("/api/v1/admin/dashboard")).status_code == 401


@pytest.mark.asyncio
async def test_request_prompt_too_long_is_413(client):
    r = await client.post("/api/v1/requests", json={"prompt": "x" * 5000})
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_request_returns_a_decision(client):
    # B1's sanitizer is implemented; with no LLM key it falls back to a heuristic classifier and
    # still returns a valid routing Decision (never a crash, never echoing the raw prompt).
    prompt = "teach me photosynthesis, grade 5"
    r = await client.post("/api/v1/requests", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] in {"proceed", "clarify", "refuse", "crisis"}
    assert "request_id" in body
    # The raw prompt must never be echoed back verbatim in the decision payload.
    assert prompt not in r.text
