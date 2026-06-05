"""Claude-SVG generator.

For SVG visual kinds (diagrams, charts, cycles, timelines, geometry, ...) we ask Claude Opus 4.8 for a
self-contained ``<svg>`` document via structured output, then run it through the server-side
:mod:`~app.visuals.svg_sanitize` before it is ever stored or served.

The B2 ``app.llm.client`` module (the AsyncAnthropic wrapper with prompt caching + ``messages.parse``)
is written concurrently with this module, so it is imported **lazily** inside the call. Tests inject a
fake client via :func:`set_svg_client` so no network call is made.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from ..core.constants import PROMPT_VERSION
from ..schemas.common import StrictModel
from ..schemas.generation import GenVisualSpec
from .svg_sanitize import sanitize_svg

_SYSTEM_PROMPT = (
    "You are an expert educational illustrator that outputs a single, self-contained, accessible SVG "
    "diagram for children's learning materials. Rules: output ONE root <svg> element with a viewBox; "
    "use only inline shapes, paths, and text; never include <script>, <foreignObject>, event handlers "
    "(on*), external images, or links to external resources. Keep it clean, colourful, uncluttered and "
    "age-appropriate. Always provide concise alt text and an optional caption."
)


class SvgGenerationOutput(StrictModel):
    """Structured output target for the Claude-SVG generator."""

    svg: str = Field(description="A single self-contained <svg> element with a viewBox.")
    alt: str = Field(description="Concise descriptive alt text for screen readers.")
    caption: str | None = Field(default=None, description="Optional short figure caption.")


class _StructuredClient(Protocol):
    """Minimal structured-output surface this module depends on from ``app.llm.client``."""

    async def parse(
        self, *, system: str, user: str, output_format: type, **kwargs: Any
    ) -> Any: ...


# Optional test/override hook. When set, used instead of importing app.llm.client.
_OVERRIDE_CLIENT: Any | None = None


def set_svg_client(client: Any | None) -> None:
    """Inject a structured-output client (used by tests / DI). Pass ``None`` to clear the override."""
    global _OVERRIDE_CLIENT
    _OVERRIDE_CLIENT = client


async def _call_structured(system: str, user: str) -> SvgGenerationOutput:
    """Invoke the structured-output client, tolerating the small API variations B2 may land with."""
    client = _OVERRIDE_CLIENT
    if client is None:
        # Lazy import: B2 owns app.llm.client and may still be in flight at import time elsewhere.
        from ..llm import client as llm_client  # type: ignore[attr-defined]

        client = llm_client

    # When no test override is set we call the real B2 wrapper directly. generate_structured returns
    # a (model, Usage) tuple, so unpack before coercing.
    if _OVERRIDE_CLIENT is None:
        result, _usage = await client.generate_structured(
            system_blocks=system,
            user=user,
            output_model=SvgGenerationOutput,
        )
        return _coerce_output(result)

    # Test/DI override exposes the minimal (system, user, output_format) parse surface.
    result = await client.parse(
        system=system, user=user, output_format=SvgGenerationOutput
    )
    return _coerce_output(result)


def _coerce_output(result: Any) -> SvgGenerationOutput:
    """Normalise whatever the client returns into a :class:`SvgGenerationOutput`."""
    if isinstance(result, SvgGenerationOutput):
        return result
    # Anthropic-style parsed response objects often carry ``.parsed``; structured wrappers may return a dict.
    parsed = getattr(result, "parsed", None)
    if isinstance(parsed, SvgGenerationOutput):
        return parsed
    if isinstance(parsed, dict):
        return SvgGenerationOutput.model_validate(parsed)
    if isinstance(result, dict):
        return SvgGenerationOutput.model_validate(result)
    raise RuntimeError("unexpected structured-output shape from app.llm.client")


def _build_user_prompt(spec: GenVisualSpec, *, language: str, grade_band: str) -> str:
    """Build the trailing user message from validated fields only — never raw student text."""
    instruction = spec.svg_request or spec.alt_text
    lines = [
        f"Create an educational SVG figure of kind: {spec.visual_kind.value}.",
        f"Instruction: {instruction}",
        f"Target reading/grade band: {grade_band}.",
        f"Respond entirely in this language: {language}.",
        f"Required alt text basis: {spec.alt_text}",
    ]
    if spec.caption:
        lines.append(f"Suggested caption: {spec.caption}")
    lines.append(f"(prompt_version={PROMPT_VERSION})")
    return "\n".join(lines)


async def generate_svg(spec: GenVisualSpec, *, language: str, grade_band: str) -> dict:
    """Generate and sanitize an SVG for ``spec``.

    Returns ``{"svg": <sanitized markup>, "alt": str, "caption": str | None}``. Raises if the model
    output cannot be made safe (the router degrades that to a placeholder)."""
    user = _build_user_prompt(spec, language=language, grade_band=grade_band)
    out = await _call_structured(_SYSTEM_PROMPT, user)

    sanitized = sanitize_svg(out.svg)
    alt = out.alt.strip() or spec.alt_text
    caption = (out.caption.strip() if out.caption else None) or spec.caption
    return {"svg": sanitized, "alt": alt, "caption": caption}
