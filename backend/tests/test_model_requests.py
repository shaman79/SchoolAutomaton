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


# --------------------------------------------------------------------------- refusal fallback billing
# Shapes from the platform docs ("Refusals and fallback"): a hop that declined is a "message" entry in
# usage.iterations, the hop that answered a "fallback_message" entry; top-level usage covers only the
# latter. A decline before any output is billed only for bio / frontier_llm / reasoning_extraction.
def _fallback_body(*, declined_output: int, category: str | None) -> dict:
    declined = {"type": "message", "model": "claude-opus-5-5", "input_tokens": 6200,
                "output_tokens": declined_output, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}
    served = {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 6100,
              "output_tokens": 4000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return {
        "id": "msg_fallback", "type": "message", "role": "assistant", "model": "claude-opus-4-8",
        "content": [
            {"type": "fallback", "from": {"model": "claude-opus-5-5"},
             "to": {"model": "claude-opus-4-8"}, "trigger": {"type": "refusal", "category": category}},
            {"type": "text", "text": '{"x": 1}'},
        ],
        "stop_reason": "end_turn", "stop_sequence": None, "stop_details": None,
        "usage": {"input_tokens": 6100, "output_tokens": 4000, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0, "iterations": [declined, served]},
    }


def _sdk_answering(body: dict):
    """The real SDK (it must keep usage.iterations and the fallback block), only the HTTP faked."""
    import anthropic
    import httpx2

    transport = httpx2.MockTransport(lambda _request: httpx2.Response(200, json=body))
    return anthropic.AsyncAnthropic(
        api_key="test-key", max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=transport),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("declined_output", "category", "billed_models"), [
    (7000, "cyber", ["claude-opus-5-5", "claude-opus-4-8"]),  # declined mid-output: billed
    (0, "cyber", ["claude-opus-4-8"]),  # declined before any output, unbilled category
    (0, "bio", ["claude-opus-5-5", "claude-opus-4-8"]),  # ...in a billed one
], ids=["mid-output", "before-output-cyber", "before-output-bio"])
async def test_a_declined_attempt_counts_toward_the_budget_when_it_is_billed(
    db, declined_output, category, billed_models
):
    from sqlalchemy import select

    from app.core.pricing import estimate_cost_usd
    from app.models import GenerationUsage
    from app.services.cost_guard import spent_today_usd

    out, usage = await cl.generate_structured(
        system_blocks="s", user="u", output_model=_Out, model="claude-opus-5-5", effort="medium",
        use_json_mode=True, db=db,
        client=_sdk_answering(_fallback_body(declined_output=declined_output, category=category)),
    )
    await db.flush()
    rows = (await db.scalars(select(GenerationUsage).order_by(GenerationUsage.id))).all()
    assert out.x == 1
    assert usage.model == "claude-opus-4-8"  # the attempt that answered
    assert [r.model for r in rows] == billed_models
    expected = sum(
        estimate_cost_usd(r.model, input_tokens=r.input_tokens, output_tokens=r.output_tokens)
        for r in rows
    )
    assert await spent_today_usd(db) == pytest.approx(expected)



# --------------------------------------------------------------------------- native structured output
class _Graded(BaseModel):
    correct: bool
    feedback: str = ""


class _Server:
    """Answers each request with the next body (the last one repeats) and records the requests."""

    def __init__(self, *bodies: dict):
        self.bodies, self.requests = list(bodies), []

    def __call__(self, request):
        import json

        import httpx2

        self.requests.append(json.loads(request.content))
        body = self.bodies[min(len(self.requests), len(self.bodies)) - 1]
        return httpx2.Response(200, json=body)


def _sdk_for(server: _Server):
    import anthropic
    import httpx2

    return anthropic.AsyncAnthropic(
        api_key="test-key", max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(server)),
    )


def _reply(text: str, *, stop_reason: str = "end_turn", output_tokens: int = 50) -> dict:
    return {
        "id": "msg_structured", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason, "stop_sequence": None, "stop_details": None,
        "usage": {"input_tokens": 900, "output_tokens": output_tokens,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }


@pytest.mark.asyncio
async def test_structured_calls_send_exactly_what_messages_parse_would():
    """Same request (so the prompt cache and the grammar are unchanged), sent with create()."""
    ours, theirs = _Server(_reply('{"correct": true}')), _Server(_reply('{"correct": true}'))
    out, _ = await cl.generate_structured(
        system_blocks="s", user="u", output_model=_Graded, model="claude-opus-5-5", effort="low",
        client=_sdk_for(ours),
    )
    assert out.correct is True
    sent = ours.requests[0]
    expected = dict(sent)
    expected.pop("output_config")
    await _sdk_for(theirs).messages.parse(
        output_format=_Graded, output_config={"effort": "low"},
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        **{k: v for k, v in expected.items() if k not in ("fallbacks",)},
        extra_body={"fallbacks": "default"},
    )
    assert sent == theirs.requests[0]


@pytest.mark.asyncio
async def test_a_cut_off_structured_answer_is_logged_once_and_not_retried():
    """messages.parse validated inside the call: a max_tokens cut-off raised before its usage was
    logged, then was retried twice as if merely invalid — three billed calls, none counted."""
    server = _Server(_reply('{"correct": true, "feedback": "Nice careful thinki', stop_reason="max_tokens",
                            output_tokens=2000))
    sink: list = []
    with pytest.raises(cl.StopReasonError):
        await cl.generate_structured(
            system_blocks="s", user="u", output_model=_Graded, model="claude-opus-5-5",
            max_tokens=2000, effort="low", client=_sdk_for(server), usage_sink=sink,
        )
    assert len(server.requests) == 1
    assert [u.output_tokens for u in sink] == [2000]


@pytest.mark.asyncio
async def test_an_answer_mentioning_thinking_never_switches_thinking_off():
    """Any error whose text contained "thinking" used to switch thinking off for the model until
    the next restart — including a validation error quoting the model's own answer."""
    cl._thinking_unsupported.discard("claude-opus-5-5")
    server = _Server(_reply('{"feedback": "Nice careful thinking!"}'), _reply('{"correct": true}'))
    out, _ = await cl.generate_structured(
        system_blocks="s", user="u", output_model=_Graded, model="claude-opus-5-5", effort="low",
        client=_sdk_for(server),
    )
    assert out.correct is True
    assert [("thinking" in r) for r in server.requests] == [True, True]
    assert "claude-opus-5-5" not in cl._thinking_unsupported
