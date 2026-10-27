"""How long and how often a failing model call is retried: a refusal or a max_tokens cut-off is not
re-sent (it would repeat, re-billing up to max_tokens of output while the child keeps waiting), a
schema slip still gets its corrective retry, and the SDK's own transport retries stay few."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.llm import client as cl  # noqa: E402


class _Out(BaseModel):
    x: int


def _client(replies: list[tuple[str, str]], calls: list[dict]):
    """A fake client returning (stop_reason, text) replies in order (JSON mode)."""

    async def create(**kw):
        calls.append(kw)
        stop, text = replies[min(len(calls), len(replies)) - 1]
        return SimpleNamespace(
            usage=None, stop_reason=stop, _request_id="r", parsed_output=None,
            content=[SimpleNamespace(type="text", text=text)],
        )

    return SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
async def test_a_stop_that_would_repeat_is_not_retried(stop):
    calls: list[dict] = []
    with pytest.raises(cl.GenerationError):
        await cl.generate_structured(
            system_blocks="s", user="u", output_model=_Out, model="m", use_json_mode=True,
            client=_client([(stop, '{"x": 1')], calls),
        )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_schema_slip_still_gets_its_corrective_retry():
    calls: list[dict] = []
    out, _ = await cl.generate_structured(
        system_blocks="s", user="u", output_model=_Out, model="m", use_json_mode=True,
        client=_client([("end_turn", '{"x": "not a number"}'), ("end_turn", '{"x": 2}')], calls),
    )
    assert out.x == 2
    assert len(calls) == 2


def test_transport_retries_stay_few(monkeypatch):
    monkeypatch.setattr(cl, "_client", None)
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "k")
    assert cl.get_client().max_retries == cl.SDK_MAX_RETRIES <= 2
