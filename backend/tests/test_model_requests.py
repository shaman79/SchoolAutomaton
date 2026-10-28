"""What each model is sent (the Opus 5.5 / Haiku 5.5 request surface differs from 4.8 / 4.5), and
what happens on a safety-classifier refusal."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import app.models  # noqa: E402,F401
from app.api.deps import RequestContext  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.llm import client as cl  # noqa: E402
from app.sanitization import ratelimit, sanitize_request  # noqa: E402
from app.schemas.intent import RefuseDecision  # noqa: E402


class _Out(BaseModel):
    x: int = 1


def _fake(calls: list[dict], *, stop="end_turn", served_by=None, details=None, tool=False):
    def message(kw):
        content = (
            [SimpleNamespace(type="tool_use", input={"x": 1})]
            if tool
            else [SimpleNamespace(type="text", text='{"x": 1}')]
        )
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=1000, output_tokens=1000), stop_reason=stop,
            stop_details=details, model=served_by or kw["model"], _request_id="r",
            parsed_output=_Out() if stop == "end_turn" else None, content=content,
        )

    async def create(**kw):
        calls.append({"api": "create", **kw})
        return message(kw)

    async def parse(**kw):
        calls.append({"api": "parse", **kw})
        return message(kw)

    return SimpleNamespace(messages=SimpleNamespace(create=create, parse=parse))


async def _run(model, *, mode="json", **fake_kw):
    calls: list[dict] = []
    out, usage = await cl.generate_structured(
        system_blocks="s", user="u", output_model=_Out, model=model, effort="medium",
        use_json_mode=mode == "json", use_tools_fallback=mode == "tools",
        use_thinking=mode != "tools", client=_fake(calls, tool=mode == "tools", **fake_kw),
    )
    return calls[0], usage


@pytest.mark.asyncio
async def test_json_mode_now_sends_the_effort_it_was_asked_for():
    """JSON mode (lessons, quizzes) sent no effort: calls ran at the model's default whatever the
    code said — on Opus 5.5 that default drops from high to medium."""
    for model in ("claude-opus-4-8", "claude-opus-5-5"):
        call, _ = await _run(model)
        assert call["output_config"] == {"effort": "medium"}
        assert call["thinking"] == {"type": "adaptive"}


@pytest.mark.asyncio
async def test_opus_5_5_opts_into_server_side_refusal_fallbacks():
    call, _ = await _run("claude-opus-5-5")
    assert call["extra_body"] == {"fallbacks": "default"}
    assert call["extra_headers"] == {"anthropic-beta": "server-side-fallback-2026-07-01"}
    old, _ = await _run("claude-opus-4-8")
    assert "extra_body" not in old


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-haiku-5-5"])
async def test_the_classifier_route_on_haiku(model):
    call, _ = await _run(model, mode="tools")
    assert call["tool_choice"] == {"type": "tool", "name": "emit_result"}  # accepted on both
    assert "thinking" not in call
    assert "extra_body" not in call  # Haiku 5.5 has no server-side fallback
    assert "output_config" not in call  # errors on Haiku 4.5; a forced call skips thinking on 5.5


@pytest.mark.asyncio
async def test_no_forced_tool_choice_where_it_400s():
    call, _ = await _run("claude-opus-5-5", mode="tools")
    assert call["tool_choice"] == {"type": "auto"}
    assert call["tools"][0]["strict"] is True


@pytest.mark.asyncio
async def test_a_refusal_carries_its_category_and_is_not_retried():
    calls: list[dict] = []
    with pytest.raises(cl.RefusalError) as info:
        await cl.generate_structured(
            system_blocks="s", user="u", output_model=_Out, model="claude-opus-5-5",
            use_json_mode=True,
            client=_fake(calls, stop="refusal", details=SimpleNamespace(category="bio")),
        )
    assert info.value.category == "bio"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cost_is_priced_by_the_model_that_answered():
    _, usage = await _run("claude-opus-5-5", served_by="claude-opus-4-8")
    assert usage.model == "claude-opus-4-8"


# --------------------------------------------------------------------------- classifier refusal
@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    ratelimit.limiter.reset()
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.mark.asyncio
async def test_a_classifier_refusal_is_a_friendly_refusal_not_an_outage(db, monkeypatch):
    """Haiku 5.5's safety layer can decline to read a prompt (and has no server-side fallback). That
    used to surface as 503 "assistant unavailable"; it's a verdict on the prompt: refuse + redirect."""
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "k")

    async def declined(**_kw):
        raise cl.RefusalError("declined", "bio")

    monkeypatch.setattr(cl, "classify", declined)
    ctx = RequestContext(ip_hash="ip-refusal", user_agent="pytest", profile_id=None)
    decision = await sanitize_request(db, "how to culture a dangerous pathogen", ctx, "rid-r")
    assert isinstance(decision, RefuseDecision)
    assert decision.redirect_suggestions
