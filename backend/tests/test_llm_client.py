"""app.llm.client resilience: the Haiku classifier must NOT send `thinking`/`output_config`
(unsupported on that model), and any model that rejects `thinking` self-heals (retry without it)."""

from __future__ import annotations

import os

os.environ.setdefault("SA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-please-ignore")
os.environ.setdefault("SA_ENV", "test")

import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.llm import client as cl  # noqa: E402
from app.schemas.intent import StructuredIntent  # noqa: E402


class _Out(BaseModel):
    x: int = 0


class _ToolBlock:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Msg:
    def __init__(self, payload):
        self.usage = None
        self.stop_reason = "end_turn"
        self._request_id = "req_test"
        self.content = [_ToolBlock(payload)]
        self.parsed_output = None


@pytest.mark.asyncio
async def test_thinking_self_heals_on_unsupported_model(monkeypatch):
    cl._thinking_unsupported.discard("some-model")
    calls: list[dict] = []

    class FakeMessages:
        async def create(self, **kw):
            calls.append(kw)
            if "thinking" in kw:
                raise RuntimeError(
                    "Error code: 400 - adaptive thinking is not supported on this model"
                )
            return _Msg({"x": 5})

    class FakeClient:
        messages = FakeMessages()

    res, _usage = await cl.generate_structured(
        system_blocks="s", user="u", output_model=_Out, model="some-model",
        use_tools_fallback=True, client=FakeClient(),
    )
    assert res.x == 5
    assert any("thinking" in c for c in calls)       # first attempt sent thinking (and 400'd)
    assert any("thinking" not in c for c in calls)   # retried without it
    assert "some-model" in cl._thinking_unsupported  # remembered


@pytest.mark.asyncio
async def test_classifier_uses_tools_and_no_thinking(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "k")
    seen: dict = {}

    class FakeMessages:
        async def create(self, **kw):
            seen.update(kw)
            return _Msg({})  # StructuredIntent() defaults validate fine

        async def parse(self, **kw):
            raise AssertionError("classifier must use tool-use, not messages.parse")

    class FakeClient:
        messages = FakeMessages()

    intent, _ = await cl.classify(
        system_blocks="sys", user="<<student_input::ab>>\nhi\n<<student_input::ab>>",
        output_model=StructuredIntent, client=FakeClient(),
    )
    assert isinstance(intent, StructuredIntent)
    assert "thinking" not in seen          # Haiku rejects adaptive thinking
    assert "output_config" not in seen     # and output_config/effort are Opus-only
    assert "tools" in seen
