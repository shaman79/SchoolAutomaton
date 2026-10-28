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
* logs a :class:`GenerationUsage` row (input / cache_creation / cache_read / output tokens, plus the
  estimated USD cost from ``core.pricing``) and asserts the cache hit/creation is observable. A
  caller that must not stage a write while the call is in flight passes ``usage_sink`` instead of
  ``db`` and stages the rows itself once the call has returned (see ``grader.py``).

The Anthropic client is created lazily and can be injected (``set_client`` / the ``client=`` arg)
so generators are unit-testable with a mock — no network, no key.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import anthropic
import pydantic
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.pricing import estimate_cost_usd
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


# The SDK retries 429/5xx/529 and timeouts with backoff. Each try may run the full request timeout,
# so 5 retries meant a child could watch the loading screen for 6 x 2 minutes before hearing it
# failed; 2 rides out a blip and keeps the worst case to minutes, not a quarter of an hour.
SDK_MAX_RETRIES = 2


def get_client() -> anthropic.AsyncAnthropic:
    """Lazily construct the shared AsyncAnthropic client (auto-retries 429/5xx/529 + timeouts).

    A request timeout is set so a single call can never hang the generation pipeline indefinitely."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or "missing-key",
            max_retries=SDK_MAX_RETRIES,
            timeout=settings.llm_request_timeout_s,
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


class StopReasonError(GenerationError):
    """The model stopped in a way the same request would only repeat (refusal, max_tokens,
    pause_turn). Not retried with a correction: a retry re-bills up to max_tokens of output and makes
    the child wait minutes longer for the same failure."""


class RefusalError(StopReasonError):
    """A safety-classifier decline (``stop_reason: "refusal"``; for Opus 5.5 after its server-side
    fallback also declined). ``category`` is informational (``bio``, ``cyber``, ``general_harms``...)."""

    def __init__(self, message: str, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category


# --------------------------------------------------------------------------- model capabilities
# What each configured model accepts. Opus 5.5 / Haiku 5.5 changed the request surface (see the
# claude-api migration guide): effort everywhere, refusals, and Opus 5.5 rejects forced tool use.
def _supports_effort(model: str) -> bool:
    """``output_config.effort`` errors on Haiku 4.5; every other model we run accepts it."""
    return not model.startswith("claude-haiku-4")


def _rejects_forced_tool_choice(model: str) -> bool:
    """Opus 5.5 / Sonnet 5.5 / Fable 5.1 400 on tool_choice any|tool (Haiku 5.5 accepts it)."""
    return model.startswith(("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"))


def _server_fallback_kwargs(model: str) -> dict[str, Any]:
    """Opt Opus 5/5.5 into server-side refusal fallbacks: a safety-classifier false positive on a
    school topic is then re-run on Anthropic's recommended fallback model inside the same call,
    instead of failing the child's lesson. (Haiku 5.5 has no server-side fallback — don't send it.)"""
    if model.startswith("claude-opus-5"):
        return {
            "extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"},
            "extra_body": {"fallbacks": "default"},
        }
    return {}


# Refusal categories billed even when the decline came before any output ("How refusals are billed",
# platform docs, as of September 2026). A pre-output decline in any other category (cyber,
# general_harms, null) is reported but not billed.
_BILLED_BEFORE_OUTPUT = frozenset({"bio", "frontier_llm", "reasoning_extraction"})


def _field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _attempt_usages(message: Any, requested_model: str, request_id: str | None) -> list[Usage]:
    """One Usage per billed attempt behind a response, each priced by the model that ran it; the
    last is the attempt that produced the returned message.

    With a server-side fallback, ``usage.iterations`` is the per-attempt billing record: each hop
    that declined is a "message" entry, the one that answered a "fallback_message" entry, and the
    top-level usage covers only that last one. A hop that declined before any output is billed only
    in some refusal categories (the k-th ``fallback`` content block names the k-th hop's). Without
    iterations, no fallback ran and the top-level usage is the whole call."""
    served_by = getattr(message, "model", None)
    served_by = served_by if isinstance(served_by, str) and served_by else requested_model
    top = getattr(message, "usage", None)
    iterations = list(_field(top, "iterations") or []) if top is not None else []
    if not iterations:
        return [_coerce_usage(top, served_by, request_id)]
    declined_because = iter([
        _field(_field(block, "trigger") or {}, "category")
        for block in (getattr(message, "content", None) or [])
        if _field(block, "type") == "fallback"
    ])
    usages: list[Usage] = []
    for entry in iterations:
        if _field(entry, "type") == "message":  # a hop that declined
            category = next(declined_because, None)
            if not _field(entry, "output_tokens") and category not in _BILLED_BEFORE_OUTPUT:
                continue  # declined before any output, in a category that isn't billed
        ran = _field(entry, "model")
        usages.append(_coerce_usage(entry, ran if isinstance(ran, str) and ran else served_by, request_id))
    return usages or [_coerce_usage(top, served_by, request_id)]


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
    """Build (do not add) a GenerationUsage row from normalized usage. cache_read>0 verifies caching.

    ``est_cost_usd`` comes from the single price table in ``core.pricing`` (None for an unknown model);
    the admin dashboard and the daily AI budget (``services.cost_guard``) sum it."""
    return GenerationUsage(
        profile_id=profile_id,
        request_id=request_id,
        provider="anthropic",
        model=usage.model,
        input_tokens=usage.input_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        output_tokens=usage.output_tokens,
        est_cost_usd=estimate_cost_usd(
            usage.model,
            input_tokens=usage.input_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            output_tokens=usage.output_tokens,
        ),
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


def _check_stop_reason(stop_reason: str | None, stop_details: Any = None) -> None:
    if stop_reason == "refusal":
        category = getattr(stop_details, "category", None)
        if category is None and isinstance(stop_details, dict):
            category = stop_details.get("category")
        raise RefusalError("Model refused to generate the requested content.", category)
    if stop_reason == "max_tokens":
        raise StopReasonError("Generation hit max_tokens before completing the structured output.")
    if stop_reason == "pause_turn":
        raise StopReasonError("Generation paused unexpectedly (pause_turn).")


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


# Models that rejected `thinking` (e.g. Haiku: "adaptive thinking is not supported on this model").
# We remember them so we stop sending it after the first rejection.
_thinking_unsupported: set[str] = set()


def _is_thinking_unsupported(exc: Exception) -> bool:
    return "thinking" in str(exc).lower()


async def _provider_call(
    cli, *, model, max_tokens, system, messages, effort, output_model, mode, send_thinking
):
    """One provider call. ``mode`` selects the output strategy:

    * ``"json"`` — plain message; the model returns JSON (the schema is in the prompt). NO grammar is
      compiled, so this is the only viable mode for big/nested content schemas (lesson/quiz) whose
      constrained-decoding grammar would exceed Anthropic's size/time cap.
    * ``"tools"`` — tool-use structured output (widely supported; used for the Haiku classifier).
    * ``"parse"`` — native structured-output parse (grammar-constrained); fine for small schemas.

    ``thinking`` is only sent when ``send_thinking``."""
    common: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        **_server_fallback_kwargs(model),
    }
    if send_thinking:
        common["thinking"] = ADAPTIVE_THINKING
    # Effort on EVERY call that accepts it — JSON mode used to omit it, so lesson/quiz calls ran at
    # the model's default (Opus 4.8: high; Opus 5.5: medium) whatever the caller asked for.
    output_config: dict[str, Any] = {"effort": effort} if _supports_effort(model) else {}
    if mode == "json":
        if output_config:
            common["output_config"] = output_config
        return await cli.messages.create(**common)
    if mode == "tools":
        tool = _tool_for(output_model)
        if _rejects_forced_tool_choice(model):
            # Forced tool use 400s here: let the model choose, with a strict schema, and say so.
            tool = {**tool, "strict": True}
            choice: dict[str, Any] = {"type": "auto"}
        else:
            choice = {"type": "tool", "name": tool["name"]}  # Haiku: forced call, no thinking
        if output_config and choice["type"] == "auto":
            common["output_config"] = output_config
        return await cli.messages.create(tools=[tool], tool_choice=choice, **common)
    if output_config:
        common["output_config"] = output_config
    return await cli.messages.parse(output_format=output_model, **common)


def _extract_json_text(message: Any) -> str:
    """Concatenate text blocks and isolate the JSON object/array (tolerant of fences / stray prose)."""
    parts = [
        getattr(b, "text", "") or ""
        for b in (getattr(message, "content", []) or [])
        if getattr(b, "type", None) == "text"
    ]
    text = "".join(parts).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    # Isolate the outermost JSON object (the model occasionally adds a lead-in sentence).
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


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
    use_thinking: bool = True,
    use_json_mode: bool = False,
    usage_sink: list[Usage] | None = None,
) -> tuple[OutputT, Usage]:
    """Run one structured Opus 4.8 call and parse it into ``output_model``.

    Retries up to ``MAX_VALIDATION_RETRIES`` on Pydantic validation failure, appending a corrective
    instruction that restates the bounds (since 4.8 strips schema min/max). Returns the validated
    model and normalized :class:`Usage`. Caching is asserted observable and logged.

    ``use_json_mode`` skips grammar-constrained decoding entirely (the schema goes in the prompt and
    we validate the returned JSON in Python). Use it for big/nested content schemas whose compiled
    grammar would exceed Anthropic's cap; keep the default (parse) for small schemas.

    ``usage_sink`` (optional) receives the :class:`Usage` of EVERY provider call made, including
    attempts that failed validation and were retried — all of them were billed. Pass it (with
    ``db=None``) to log usage yourself after the call returns instead of having a row staged on the
    session between retries.
    """
    # Fail fast with a clear, actionable error only when there is genuinely no client available:
    # no explicit client arg, no injected singleton (tests use set_client), and no API key.
    if client is None and _client is None and not settings.anthropic_api_key:
        raise GenerationError(
            "The AI service is not configured: ANTHROPIC_API_KEY is missing on the server. "
            "Set it in .env (and REPLICATE_API_TOKEN for images), then redeploy."
        )
    cli = client or get_client()
    model = model or settings.model_id
    system = _system_blocks(system_blocks)
    mode = "json" if use_json_mode else ("tools" if use_tools_fallback else "parse")

    # In JSON mode the schema lives in the prompt (no grammar compiled). Keep it stable across the
    # cached system prefix by putting it in the user message.
    json_suffix = ""
    if mode == "json":
        schema = json.dumps(output_model.model_json_schema(), separators=(",", ":"))
        json_suffix = (
            "\n\nRespond with ONLY a single JSON object that conforms to this JSON Schema. Output "
            "raw JSON with no markdown fences and no prose before or after it.\nJSON Schema:\n"
            + schema
        )

    last_error: Exception | None = None
    correction = ""

    for _attempt in range(MAX_VALIDATION_RETRIES + 1):
        user_text = f"{user}{json_suffix}"
        if correction:
            user_text = f"{user_text}\n\n{correction}"
        messages = [{"role": "user", "content": user_text}]

        try:
            # The provider call AND its parse/validate live inside the try so a pydantic
            # ValidationError raised by messages.parse (the SDK validates synchronously during the
            # await) triggers the corrective-instruction retry instead of escaping (SPEC §5).
            send_thinking = use_thinking and model not in _thinking_unsupported
            call_kwargs = {
                "model": model, "max_tokens": max_tokens, "system": system, "messages": messages,
                "effort": effort, "output_model": output_model, "mode": mode,
            }
            try:
                message = await _provider_call(cli, send_thinking=send_thinking, **call_kwargs)
            except Exception as exc:  # noqa: BLE001
                # Some models reject `thinking` (e.g. Haiku). Self-heal: remember + retry without it.
                if send_thinking and _is_thinking_unsupported(exc):
                    _thinking_unsupported.add(model)
                    message = await _provider_call(cli, send_thinking=False, **call_kwargs)
                else:
                    raise

            raw_request_id = (
                getattr(message, "_request_id", None)
                or getattr(message, "id", None)
            )
            # Every billed attempt, each priced by the model that ran it (a server-side fallback may
            # have run a declined attempt first); `usage` is the one that answered.
            attempts = _attempt_usages(message, model, raw_request_id)
            usage = attempts[-1]
            for billed in attempts:
                if usage_sink is not None:
                    usage_sink.append(billed)
                _log_usage(db, billed, request_id=request_id, profile_id=profile_id)

            _check_stop_reason(
                getattr(message, "stop_reason", None), getattr(message, "stop_details", None)
            )

            if mode == "json":
                text = _extract_json_text(message)
                if not text:
                    raise GenerationError("Empty response in JSON mode.")
                result = output_model.model_validate_json(text)
            elif mode == "tools":
                payload = _extract_tool_payload(message)
                if payload is None:
                    raise GenerationError("No tool_use block in response.")
                result = output_model.model_validate(payload)
            else:
                result = _extract_parsed(message, output_model)
                if result is None:
                    raise GenerationError("No parsable structured output in response.")
        except StopReasonError:
            raise
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
        # Haiku-safe: tool-use structured output, no `thinking`/`output_config` (Opus-only features).
        use_tools_fallback=True,
        use_thinking=False,
    )
