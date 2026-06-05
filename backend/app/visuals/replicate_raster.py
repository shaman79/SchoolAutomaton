"""Replicate raster generator (hosted Flux models).

For raster visual kinds (illustration / scene / character / photo) we render a kid-safe image on
Replicate. The prompt is ALWAYS a rewrite assembled from validated fields via
:data:`~app.core.constants.REPLICATE_PROMPT_TEMPLATE` + :data:`REPLICATE_NEGATIVE_CLAUSE` — never raw
student text (one-way-flow invariant). Model tier, aspect ratio and megapixels come from
``LAYOUT_SLOT_SPECS``; output is webp; ``safety_tolerance`` is strict.

Replicate's output URLs expire, so the router persists the returned bytes to the on-disk cache
immediately. The replicate SDK (>=1.0) ``async_run`` returns a ``FileOutput`` we ``aread()`` for bytes.

Tests inject a fake runner via :func:`set_replicate_runner`; no live call is made (no token).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.config import settings
from ..core.constants import (
    LAYOUT_SLOT_SPECS,
    REPLICATE_MODELS_DEFAULT,
    REPLICATE_NEGATIVE_CLAUSE,
    REPLICATE_PROMPT_TEMPLATE,
)
from ..schemas.enums import LayoutSlot
from ..schemas.generation import GenVisualSpec

OUTPUT_FORMAT = "webp"
OUTPUT_MIME = "image/webp"
DEFAULT_SEED = 0  # deterministic by default → identical requests cache to one asset


class VideoDisabledError(RuntimeError):
    """Raised when a video kind is requested but ``settings.video_enabled`` is off (router → SVG fallback)."""


@dataclass
class RasterResult:
    """Bytes + provenance returned by :func:`generate_raster` (router persists these)."""

    data: bytes
    model: str
    model_version: str | None
    prompt: str
    params: dict[str, Any]
    seed: int
    output_format: str
    mime: str
    width: int | None = None
    height: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# Optional test/DI hook: an async callable ``runner(ref, input) -> bytes | FileOutput | str | list``.
_OVERRIDE_RUNNER: Any | None = None


def set_replicate_runner(runner: Any | None) -> None:
    """Inject an async runner ``(ref, input=...) -> output`` (used by tests). ``None`` clears it."""
    global _OVERRIDE_RUNNER
    _OVERRIDE_RUNNER = runner


def build_prompt(spec: GenVisualSpec, *, grade_band: str) -> str:
    """Assemble the kid-safe Replicate prompt from validated fields only.

    ``subject`` is taken from the validated ``image_prompt`` (a kid-safe rewrite produced upstream by
    B2) or falls back to the alt text — never from raw student input.
    """
    subject = (spec.image_prompt or spec.alt_text or "an educational subject").strip()
    positive = REPLICATE_PROMPT_TEMPLATE.format(subject=subject, grade=grade_band)
    return f"{positive} {REPLICATE_NEGATIVE_CLAUSE}"


def _slot_spec(spec: GenVisualSpec) -> dict[str, Any]:
    slot = spec.layout_slot.value if isinstance(spec.layout_slot, LayoutSlot) else str(spec.layout_slot)
    return LAYOUT_SLOT_SPECS.get(slot, LAYOUT_SLOT_SPECS[LayoutSlot.INLINE_FIGURE.value])


def select_model(spec: GenVisualSpec) -> str:
    """Pick the Replicate model ref for ``spec`` based on its layout slot tier."""
    tier = _slot_spec(spec).get("tier", "default")
    return REPLICATE_MODELS_DEFAULT.get(tier, REPLICATE_MODELS_DEFAULT["default"])


def build_input(spec: GenVisualSpec, prompt: str) -> dict[str, Any]:
    """Build the model input payload (deterministic + strictly safety-gated)."""
    slot = _slot_spec(spec)
    return {
        "prompt": prompt,
        "aspect_ratio": slot.get("aspect", "4:3"),
        "megapixels": slot.get("megapixels", 1.0),
        "output_format": OUTPUT_FORMAT,
        "output_quality": 90,
        "num_outputs": 1,
        "safety_tolerance": 1,        # strictest
        "disable_safety_checker": False,
        "seed": DEFAULT_SEED,
    }


async def _extract_bytes(output: Any) -> bytes:
    """Coerce a replicate ``async_run`` result into raw image bytes.

    Handles: raw ``bytes``; a ``FileOutput`` (``await .aread()`` / ``.read()``); a list of any of those
    (we take the first); or an ``httpx``-style URL string fetched with the replicate-shared client.
    """
    if isinstance(output, (bytes, bytearray)):
        return bytes(output)

    if isinstance(output, (list, tuple)):
        if not output:
            raise RuntimeError("replicate returned an empty output list")
        return await _extract_bytes(output[0])

    # FileOutput exposes async aread() (preferred) or sync read().
    aread = getattr(output, "aread", None)
    if callable(aread):
        return bytes(await aread())
    read = getattr(output, "read", None)
    if callable(read):
        data = read()
        return bytes(data)

    if isinstance(output, str) and output.startswith(("http://", "https://")):
        import httpx

        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.get(output)
            resp.raise_for_status()
            return resp.content

    raise RuntimeError(f"cannot extract bytes from replicate output of type {type(output)!r}")


async def _run(ref: str, model_input: dict[str, Any]) -> Any:
    """Call the injected runner, else the replicate async API with the configured token."""
    if _OVERRIDE_RUNNER is not None:
        return await _OVERRIDE_RUNNER(ref, input=model_input)

    import replicate  # lazy: keep import-time cheap and avoid touching token until needed

    client = replicate.Client(api_token=settings.replicate_api_token or None)
    return await client.async_run(ref, input=model_input, use_file_output=True)


async def generate_raster(spec: GenVisualSpec, *, grade_band: str) -> RasterResult:
    """Generate a kid-safe raster image for ``spec`` and return its bytes + provenance.

    Video gating (``settings.video_enabled``) is enforced upstream by the router, which falls back to
    an SVG placeholder when video is off (default-off cost guardrail, SPEC §4 #4 / §9)."""
    ref = select_model(spec)
    prompt = build_prompt(spec, grade_band=grade_band)
    model_input = build_input(spec, prompt)

    output = await _run(ref, model_input)
    data = await _extract_bytes(output)
    if not data:
        raise RuntimeError("replicate returned no image bytes")

    return RasterResult(
        data=data,
        model=ref,
        model_version=None,
        prompt=prompt,
        params=model_input,
        seed=model_input["seed"],
        output_format=OUTPUT_FORMAT,
        mime=OUTPUT_MIME,
    )
