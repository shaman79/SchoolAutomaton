"""Admin → Settings: see what the backend runs with, change the models / daily budget at runtime.

Precedence: an admin change > the server's environment / .env > the app default. A change applies to
the very next AI call, survives a restart, and "undo" returns to what the process started with."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import Settings, settings
from app.core.constants import PROMPT_VERSION
from app.core.pricing import price_for
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.llm import client as llm_client
from app.models import AdminUser, AppSetting, GenerationUsage
from app.services import cost_guard, runtime_settings

API = "/api/v1/admin"
EDITABLE = runtime_settings.EDITABLE_KEYS


@pytest.fixture(autouse=True)
def _defaults_only():
    """Start every test from the app defaults, as if no environment variable set an editable setting
    (the developer's own .env must not decide the outcome), and leave the shared ``settings`` object
    exactly as found."""
    saved_values = {k: getattr(settings, k) for k in EDITABLE}
    saved_provided = set(settings.__pydantic_fields_set__)
    saved_state = runtime_settings._state
    for key in EDITABLE:
        setattr(settings, key, Settings.model_fields[key].default)
    settings.__pydantic_fields_set__.difference_update(EDITABLE)
    runtime_settings._state = None
    yield
    for key, value in saved_values.items():
        setattr(settings, key, value)
    settings.__pydantic_fields_set__.clear()
    settings.__pydantic_fields_set__.update(saved_provided)
    runtime_settings._state = saved_state


async def _token(client, username="admin", password="admin12345") -> dict[str, str]:
    r = await client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _viewer(client) -> dict[str, str]:
    async with SessionLocal() as db:
        db.add(AdminUser(username="viewer", password_hash=hash_password("viewer12345"), role="viewer"))
        await db.commit()
    return await _token(client, "viewer", "viewer12345")


def _item(body: dict, key: str) -> dict:
    return next(i for i in body["items"] if i["key"] == key)


class _Out(BaseModel):
    x: int = 1


def _recording_client(calls: list[dict]):
    async def create(**kw):
        calls.append(kw)
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=10), stop_reason="end_turn",
            stop_details=None, model=kw["model"], _request_id="r", parsed_output=_Out(),
            # A tool call (the input check uses tool use) and the JSON text (everything else).
            content=[SimpleNamespace(type="tool_use", input={"x": 1}),
                     SimpleNamespace(type="text", text='{"x": 1}')],
        )

    return SimpleNamespace(messages=SimpleNamespace(create=create))


# ----------------------------------------------------------------------------------------- reading


@pytest.mark.asyncio
async def test_config_needs_an_admin_login(client):
    assert (await client.get(f"{API}/config")).status_code == 401
    assert (await client.put(f"{API}/config/model_id", json={"value": "claude-opus-4-8"})).status_code == 401
    assert (await client.delete(f"{API}/config/model_id")).status_code == 401


@pytest.mark.asyncio
async def test_config_shows_the_settings_in_effect_and_where_they_come_from(client):
    r = await client.get(f"{API}/config", headers=await _token(client))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_edit"] is True

    model = _item(body, "model_id")
    assert model["value"] == settings.model_id == "claude-opus-5-5"
    assert model["source"] == "default" and model["base_source"] == "default"
    assert model["editable"] is True and model["env_name"] == "SA_MODEL_ID"
    assert model["choices"] == list(runtime_settings.MAIN_MODELS)
    assert model["default_value"] == "claude-opus-5-5"
    assert _item(body, "sanitizer_model_id")["value"] == "claude-haiku-5-5"

    budget = _item(body, "daily_budget_usd")
    assert budget["value"] == 100.0 and budget["min"] == 0 and budget["max"] == runtime_settings.BUDGET_MAX_USD

    limit = _item(body, "rate_per_min")
    assert limit["editable"] is False and limit["value"] == settings.rate_per_min
    assert limit["env_name"] == "SA_RATE_PER_MIN"
    version = _item(body, "prompt_version")
    assert version["value"] == PROMPT_VERSION and version["source"] == "code"
    assert [i["key"] for i in body["items"]] == [s.key for s in runtime_settings.SPECS]


@pytest.mark.asyncio
async def test_api_keys_are_only_reported_as_set_never_shown(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test-SECRET-value")
    monkeypatch.setattr(settings, "replicate_api_token", "")
    r = await client.get(f"{API}/config", headers=await _token(client))
    assert "SECRET" not in r.text
    assert _item(r.json(), "anthropic_api_key")["value"] is True
    assert _item(r.json(), "replicate_api_token")["value"] is False


@pytest.mark.asyncio
async def test_a_value_from_the_server_env_is_labelled_so(client):
    # As in production, where the .env made from the old template pins the previous models.
    settings.model_id = "claude-opus-4-8"  # (an assignment marks the field as provided, like the env)
    runtime_settings._state = None
    r = await client.get(f"{API}/config", headers=await _token(client))
    model = _item(r.json(), "model_id")
    assert model["value"] == "claude-opus-4-8"
    assert model["source"] == model["base_source"] == "env"
    assert model["base_value"] == "claude-opus-4-8" and model["default_value"] == "claude-opus-5-5"


@pytest.mark.asyncio
async def test_usage_today_lists_each_model_that_answered(client):
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        db.add_all([
            GenerationUsage(provider="anthropic", model="claude-opus-5-5", est_cost_usd=0.10, created_at=now),
            GenerationUsage(provider="anthropic", model="claude-opus-5-5", est_cost_usd=0.20, created_at=now),
            GenerationUsage(provider="anthropic", model="claude-haiku-5-5", est_cost_usd=0.001, created_at=now),
            GenerationUsage(provider="replicate", model="some/image-model", est_cost_usd=None, created_at=now),
            # Yesterday: not today's.
            GenerationUsage(provider="anthropic", model="claude-opus-4-8", est_cost_usd=5.0,
                            created_at=now - timedelta(days=1, hours=1)),
        ])
        await db.commit()
    body = (await client.get(f"{API}/config", headers=await _token(client))).json()
    usage = {u["model"]: u for u in body["usage_today"]}
    assert set(usage) == {"claude-opus-5-5", "claude-haiku-5-5", "some/image-model"}
    assert usage["claude-opus-5-5"]["calls"] == 2 and usage["claude-opus-5-5"]["cost_usd"] == pytest.approx(0.3)
    assert usage["some/image-model"]["cost_usd"] is None
    assert body["usage_today"][0]["model"] == "claude-opus-5-5"  # costliest first
    assert usage["claude-opus-5-5"]["last_call_at"].endswith(("+00:00", "Z"))
    assert body["spent_today_usd"] == pytest.approx(0.301)
    assert body["budget_usd"] == 100.0
    assert body["day_started_at"].startswith(now.date().isoformat())


# ---------------------------------------------------------------------------------------- changing


@pytest.mark.asyncio
async def test_changing_the_model_reaches_the_very_next_ai_call(client):
    headers = await _token(client)
    r = await client.put(f"{API}/config/model_id", json={"value": "claude-opus-4-8"}, headers=headers)
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["value"] == "claude-opus-4-8" and item["source"] == "admin"
    assert item["updated_by"] == "admin" and item["updated_at"]
    assert item["base_value"] == "claude-opus-5-5" and item["base_source"] == "default"
    assert settings.model_id == "claude-opus-4-8"

    r = await client.put(f"{API}/config/sanitizer_model_id", json={"value": "claude-haiku-4-5"}, headers=headers)
    assert r.status_code == 200, r.text

    calls: list[dict] = []
    await llm_client.generate_structured(
        system_blocks="s", user="u", output_model=_Out, effort="medium", client=_recording_client(calls)
    )
    await llm_client.classify(system_blocks="s", user="u", output_model=_Out, client=_recording_client(calls))
    assert [c["model"] for c in calls] == ["claude-opus-4-8", "claude-haiku-4-5"]

    async with SessionLocal() as db:
        rows = {r.key: r.value_json for r in await db.scalars(select(AppSetting))}
    assert rows == {"model_id": "claude-opus-4-8", "sanitizer_model_id": "claude-haiku-4-5"}


@pytest.mark.asyncio
async def test_an_admin_change_beats_the_server_env_and_undo_returns_to_it(client):
    settings.model_id = "claude-opus-4-8"  # pinned by the server's .env
    runtime_settings._state = None
    headers = await _token(client)
    r = await client.put(f"{API}/config/model_id", json={"value": "claude-opus-5-5"}, headers=headers)
    assert r.json()["source"] == "admin" and settings.model_id == "claude-opus-5-5"

    r = await client.delete(f"{API}/config/model_id", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "claude-opus-4-8" and r.json()["source"] == "env"
    assert r.json()["updated_by"] is None
    assert settings.model_id == "claude-opus-4-8"
    async with SessionLocal() as db:
        assert await db.get(AppSetting, "model_id") is None


@pytest.mark.asyncio
async def test_the_daily_budget_change_is_what_the_cap_uses(client):
    headers = await _token(client)
    r = await client.put(f"{API}/config/daily_budget_usd", json={"value": 0.25}, headers=headers)
    assert r.status_code == 200 and r.json()["value"] == 0.25
    async with SessionLocal() as db:
        db.add(GenerationUsage(provider="anthropic", model="claude-opus-5-5", est_cost_usd=0.30))
        await db.commit()
        assert await cost_guard.ai_budget_exceeded(db) is True
    r = await client.put(f"{API}/config/daily_budget_usd", json={"value": 0}, headers=headers)  # 0 = no cap
    assert r.status_code == 200
    async with SessionLocal() as db:
        assert await cost_guard.ai_budget_exceeded(db) is False
    assert (await client.get(f"{API}/config", headers=headers)).json()["budget_usd"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("model_id", "claude-opus-3"),  # not on the list: a typo would fail every lesson
        ("model_id", "claude-haiku-5-5"),  # the input-check model can't write lessons
        ("sanitizer_model_id", "claude-opus-5-5"),
        ("model_id", 5),
        ("daily_budget_usd", -1),
        ("daily_budget_usd", runtime_settings.BUDGET_MAX_USD + 1),
        ("daily_budget_usd", "100"),
        ("daily_budget_usd", True),
    ],
)
async def test_invalid_values_are_refused_and_change_nothing(client, key, value):
    before = getattr(settings, key)
    r = await client.put(f"{API}/config/{key}", json={"value": value}, headers=await _token(client))
    assert r.status_code == 422, r.text
    assert getattr(settings, key) == before
    async with SessionLocal() as db:
        assert await db.get(AppSetting, key) is None


@pytest.mark.asyncio
async def test_only_the_models_and_budget_can_be_changed(client):
    headers = await _token(client)
    r = await client.put(f"{API}/config/rate_per_min", json={"value": 5}, headers=headers)
    assert r.status_code == 400
    r = await client.put(f"{API}/config/anthropic_api_key", json={"value": "sk-x"}, headers=headers)
    assert r.status_code == 400
    assert (await client.put(f"{API}/config/nope", json={"value": 1}, headers=headers)).status_code == 404
    assert (await client.delete(f"{API}/config/rate_per_min", headers=headers)).status_code == 400
    # Unknown fields in the body are refused, and the old free-form settings store is gone.
    r = await client.put(f"{API}/config/model_id", json={"value": "claude-opus-4-8", "is_secret": True},
                         headers=headers)
    assert r.status_code == 422
    assert (await client.get(f"{API}/settings", headers=headers)).status_code in (404, 405)
    assert (await client.put(f"{API}/settings", json={"key": "a", "value": 1}, headers=headers)).status_code in (404, 405)


@pytest.mark.asyncio
async def test_a_read_only_admin_can_look_but_not_change(client):
    headers = await _viewer(client)
    r = await client.get(f"{API}/config", headers=headers)
    assert r.status_code == 200 and r.json()["can_edit"] is False
    r = await client.put(f"{API}/config/model_id", json={"value": "claude-opus-4-8"}, headers=headers)
    assert r.status_code == 403
    assert (await client.delete(f"{API}/config/model_id", headers=headers)).status_code == 403
    assert settings.model_id == "claude-opus-5-5"


# ---------------------------------------------------------------------------------------- restarts


@pytest.mark.asyncio
async def test_admin_changes_come_back_after_a_restart(client):
    from app.main import _load_admin_settings  # noqa: PLC0415

    headers = await _token(client)
    await client.put(f"{API}/config/model_id", json={"value": "claude-opus-4-8"}, headers=headers)
    await client.put(f"{API}/config/daily_budget_usd", json={"value": 42.5}, headers=headers)

    # A restart: the process starts on the defaults again, then startup re-applies what is stored.
    runtime_settings.reset_for_tests()
    runtime_settings._state = None
    settings.__pydantic_fields_set__.difference_update(EDITABLE)  # a fresh process: nothing from the env
    assert settings.model_id == "claude-opus-5-5" and settings.daily_budget_usd == 100.0
    await _load_admin_settings()
    assert settings.model_id == "claude-opus-4-8" and settings.daily_budget_usd == 42.5
    body = (await client.get(f"{API}/config", headers=headers)).json()
    assert _item(body, "model_id")["source"] == "admin"
    assert _item(body, "model_id")["updated_by"] == "admin"


@pytest.mark.asyncio
async def test_a_stored_value_this_release_no_longer_allows_is_skipped(client, caplog):
    async with SessionLocal() as db:
        db.add(AppSetting(key="model_id", value_json="claude-opus-3", is_secret=False))
        db.add(AppSetting(key="daily_budget_usd", value_json=12, is_secret=False))
        db.add(AppSetting(key="something_else", value_json="x", is_secret=False))
        await db.commit()
        with caplog.at_level(logging.WARNING, logger="schoolautomaton.admin"):
            applied = await runtime_settings.load_overrides(db)
    assert applied == 1
    assert settings.model_id == "claude-opus-5-5" and settings.daily_budget_usd == 12.0
    assert "claude-opus-3" in caplog.text
    body = (await client.get(f"{API}/config", headers=await _token(client))).json()
    assert _item(body, "model_id")["source"] == "default"  # what really runs, not what is stored
    assert _item(body, "daily_budget_usd")["source"] == "admin"


@pytest.mark.asyncio
async def test_startup_survives_a_broken_settings_table(monkeypatch, caplog):
    from app import main  # noqa: PLC0415

    async def boom(db):
        raise RuntimeError("table is broken")

    monkeypatch.setattr(runtime_settings, "load_overrides", boom)
    with caplog.at_level(logging.ERROR):
        await main._load_admin_settings()  # must not raise
    assert "Could not load the admin settings" in caplog.text


# ------------------------------------------------------------------------------------- the choices


def test_every_offered_model_is_priced_and_the_defaults_are_offered():
    # Unpriced calls cost NULL and would slip past the daily budget.
    for model in (*runtime_settings.MAIN_MODELS, *runtime_settings.SANITIZER_MODELS):
        assert price_for(model) is not None, model
    assert Settings.model_fields["model_id"].default == runtime_settings.MAIN_MODELS[0]
    assert Settings.model_fields["sanitizer_model_id"].default == runtime_settings.SANITIZER_MODELS[0]
    assert Settings.model_fields["daily_budget_usd"].default <= runtime_settings.BUDGET_MAX_USD


@pytest.mark.asyncio
async def test_admin_timestamps_carry_their_utc_zone(client):
    # Without a zone the browser reads a stored UTC time as its own local time (an hour off in Prague).
    from app.models import SanitizationAudit  # noqa: PLC0415

    async with SessionLocal() as db:
        db.add(SanitizationAudit(request_id="r1", ip_hash="x" * 64, classifier_verdict_json={},
                                 decision_type="proceed", model_id="m", prompt_version="v"))
        await db.commit()
    r = await client.get(f"{API}/audit", headers=await _token(client))
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["ts"].endswith(("+00:00", "Z"))
