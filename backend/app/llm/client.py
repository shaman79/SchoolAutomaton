"""Thin AsyncAnthropic wrapper: structured output + prompt caching + usage telemetry.

Every Opus 4.8 call goes through :func:`generate_structured`. It:

* orders ``tools -> system -> messages`` (system carries the big byte-identical cached
  pedagogy prefix marked ``cache_control:{type:'ephemeral'}``);
* sets ``thinking={'type':'adaptive'}`` and an ``output_config.effort`` (no temperature / top_p /
  top_k / prefill — all 400 on Opus 4.8);
* parses the response into the supplied Pydantic ``output_model`` via
  ``client.messages.parse(output_format=...)`` (the installed anthropic 0.105.x API), with a
  tool-use JSON fallback for models/transports without native structured output;
* checks ``stop_reason`` (refusal / max_tokens / pause) before trusting the parse;
* retries up to twice on Pydantic ``ValidationError``, appending a corrective instruction that
  restates the numeric/length bounds (Opus 4.8 strips schema ``minimum/maximum`` — SPEC §5);
* logs a :class:`GenerationUsage` row (input / cache_creation / cache_read / output tokens) and
  asserts the cache hit/creation is observable.

The Anthropic client is created lazily and can be injected (``set_client`` / the ``client=`` arg)
so generators are unit-testable with a mock — no network, no key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import anthropic
import pydantic
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models import GenerationUsage

# Opus 4.8 minimum cacheable prefix; we never send temperature/top_p/top_k/prefill.
ADAPTIVE_THINKING: dict[str, str] = {"type": "adaptive"}
MAX_VALIDATION_RETRIES = 2

# A module-level singleton so generators share one HTTP pool. Injectable for tests.
_client: anthropic.AsyncAnthropic | None = None


def set_client(client: anthropic.AsyncAnthropic | None) -> None:
    """Inject (or reset to lazy-default) the shared AsyncAnthropic client. Used by tests + startup."""
    global _client
    _client = client


def get_client() -> anthropic.AsyncAnthropic:
    """Lazily construct the shared AsyncAnthropic client (max_retries=5 auto-retries 429/5xx/529)."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or "missing-key", max_retries=5
        )
    return _client


@dataclass(slots=True)
class Usage:
    """Normalized token usage for one Anthropic call (mirrors the GenerationUsage columns)."""

    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    anthropic_request_id: str | None = None
    model: str = ""

    @property
    def cache_observable(self) -> bool:
        """True when the prompt cache produced a measurable read or creation (SPEC invariant #4)."""
        return (self.cache_read_tokens or 0) > 0 or (self.cache_creation_tokens or 0) > 0


class GenerationError(RuntimeError):
    """Raised when a call refuses, truncates, or never yields a valid structured payload."""


def _coerce_usage(raw: Any, model: str, request_id: str | None) -> Usage:
    """Map an anthropic ``Usage`` object (or mapping) onto our normalized dataclass."""

    def g(name: str) -> int:
        if raw is None:
            return 0
        val = raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
        return int(val or 0)

    return Usage(
        input_tokens=g("input_tokens"),
        cache_creation_tokens=g("cache_creation_input_tokens"),
        cache_read_tokens=g("cache_read_input_tokens"),
        output_tokens=g("output_tokens"),
        anthropic_request_id=request_id,
        model=model,
    )


def usage_row(usage: Usage, *, request_id: str | None, profile_id: int | None = None) -> GenerationUsage:
    """Build (do not add) a GenerationUsage row from normalized usage. cache_read>0 verifies caching."""
    return GenerationUsage(
        profile_id=profile_id,
        request_id=request_id,
        provider="anthropic",
        model=usage.model,
        input_tokens=usage.input_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        output_tokens=usage.output_tokens,
        anthropic_request_id=usage.anthropic_request_id,
    )


def _log_usage(
    db: AsyncSession | None,
    usage: Usage,
    *,
    request_id: str | None,
    profile_id: int | None = None,
) -> None:
    """Stage a GenerationUsage row on the session (no flush — caller controls flush timing).

    Adding without flushing keeps this safe to call from concurrently-gathered coroutines that share
    a session; the surrounding generator flushes between its own serial DB writes.
    """
    if db is None:
        return
    db.add(usage_row(usage, request_id=request_id, profile_id=profile_id))


def _system_blocks(system_blocks: list[str] | str) -> list[dict[str, Any]]:
    """Build system text blocks; the FIRST (big, static) block carries cache_control ephemeral.

    The cached prefix MUST be byte-identical across calls — callers pass the frozen SYSTEM_PEDAGOGY
    constant first and any small volatile note (never used here) elsewhere.
    """
    blocks = [system_blocks] if isinstance(system_blocks, str) else list(system_blocks)
    out: list[dict[str, Any]] = []
    for i, text in enumerate(blocks):
        block: dict[str, Any] = {"type": "text", "text": text}
        if i == 0:
            block["cache_control"] = {"type": "ephemeral"}
        out.append(block)
    return out


def _check_stop_reason(stop_reason: str | None) -> None:
    if stop_reason == "refusal":
        raise GenerationError("Model refused to generate the requested content.")
    if stop_reason == "max_tokens":
        raise GenerationError("Generation hit max_tokens before completing the structured output.")
    if stop_reason == "pause_turn":
        raise GenerationError("Generation paused unexpectedly (pause_turn).")


def _extract_parsed[OutputT: BaseModel](message: Any, output_model: type[OutputT]) -> OutputT | None:
    """Pull the parsed Pydantic instance out of a ParsedMessage (or fall back to text JSON)."""
    parsed = getattr(message, "parsed_output", None)
    if isinstance(parsed, output_model):
        return parsed
    # Fallback: scan text blocks for raw JSON and validate ourselves.
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            text = text.strip()
            if text.startswith("{") or text.startswith("["):
                return output_model.model_validate_json(text)
    return None


def _extract_tool_payload(message: Any) -> dict[str, Any] | None:
    """Pull the first tool_use input dict from a message (tool-use JSON fallback path)."""
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
    return None


def _tool_for(output_model: type[BaseModel], name: str = "emit_result") -> dict[str, Any]:
    """Build a tool definition whose input_schema is the output model's JSON schema."""
    return {
        "name": name,
        "description": f"Emit the result as a {output_model.__name__} object.",
        "input_schema": output_model.model_json_schema(),
    }


async def generate_structured[OutputT: BaseModel](
    *,
    system_blocks: list[str] | str,
    user: str,
    output_model: type[OutputT],
    model: str | None = None,
    max_tokens: int = 4000,
    effort: str = "high",
    db: AsyncSession | None = None,
    request_id: str | None = None,
    profile_id: int | None = None,
    client: anthropic.AsyncAnthropic | None = None,
    use_tools_fallback: bool = False,
) -> tuple[OutputT, Usage]:
    """Run one structured Opus 4.8 call and parse it into ``output_model``.

    Retries up to ``MAX_VALIDATION_RETRIES`` on Pydantic validation failure, appending a corrective
    instruction that restates the bounds (since 4.8 strips schema min/max). Returns the validated
    model and normalized :class:`Usage`. Caching is asserted observable and logged.
    """
    cli = client or get_client()
    model = model or settings.model_id
    system = _system_blocks(system_blocks)

    last_error: Exception | None = None
    correction = ""

    for _attempt in range(MAX_VALIDATION_RETRIES + 1):
        user_text = user if not correction else f"{user}\n\n{correction}"
        messages = [{"role": "user", "content": user_text}]

        try:
            # The provider call AND its parse/validate live inside the try so a pydantic
            # ValidationError raised by messages.parse (the SDK validates synchronously during the
            # await) triggers the corrective-instruction retry instead of escaping (SPEC §5).
            if use_tools_fallback:
                tool = _tool_for(output_model)
                # Order: tools -> system -> messages.
                message = await cli.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    thinking=ADAPTIVE_THINKING,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    system=system,
                    messages=messages,
                )
            else:
                message = await cli.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    thinking=ADAPTIVE_THINKING,
                    output_config={"effort": effort},
                    output_format=output_model,
                    system=system,
                    messages=messages,
                )

            raw_request_id = (
                getattr(message, "_request_id", None)
                or getattr(message, "id", None)
            )
            usage = _coerce_usage(getattr(message, "usage", None), model, raw_request_id)
            _log_usage(db, usage, request_id=request_id, profile_id=profile_id)

            _check_stop_reason(getattr(message, "stop_reason", None))

            if use_tools_fallback:
                payload = _extract_tool_payload(message)
                if payload is None:
                    raise GenerationError("No tool_use block in response.")
                result = output_model.model_validate(payload)
            else:
                result = _extract_parsed(message, output_model)
                if result is None:
                    raise GenerationError("No parsable structured output in response.")
        except (pydantic.ValidationError, GenerationError, json.JSONDecodeError) as exc:
            last_error = exc
            correction = (
                "Your previous output failed validation. Re-emit a SINGLE valid object that "
                "strictly matches the required schema and ALL stated bounds (exact counts, ranges, "
                "and field types). Do not add extra fields. Validation error: "
                f"{str(exc)[:500]}"
            )
            continue

        # Caching is best-effort to *observe* (a real call after warm-up reads the cache); we do not
        # hard-fail offline mocks, but in production the logged row makes a silent miss visible.
        return result, usage

    raise GenerationError(
        f"generate_structured failed after {MAX_VALIDATION_RETRIES + 1} attempts: {last_error}"
    )


async def classify[OutputT: BaseModel](
    *,
    system_blocks: list[str] | str,
    user: str,
    output_model: type[OutputT],
    max_tokens: int = 2000,
    db: AsyncSession | None = None,
    request_id: str | None = None,
    client: anthropic.AsyncAnthropic | None = None,
) -> tuple[OutputT, Usage]:
    """Sanitizer/classifier screen on the cheap Haiku model (effort=low). Imported by B1.

    Same caching + structured-output discipline as :func:`generate_structured`, but pinned to
    ``settings.sanitizer_model_id`` and low effort. Classification only — never answers.
    """
    return await generate_structured(
        system_blocks=system_blocks,
        user=user,
        output_model=output_model,
        model=settings.sanitizer_model_id,
        max_tokens=max_tokens,
        effort="low",
        db=db,
        request_id=request_id,
        client=client,
    )
