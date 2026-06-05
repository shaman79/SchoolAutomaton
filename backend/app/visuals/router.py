"""Visual pipeline router — the body of :func:`app.visuals.ensure_visual`.

Routing by ``spec.visual_kind``:
  * ``SVG_VISUAL_KINDS``       → Claude-SVG (asset_type ``svg``; stored inline + on disk),
  * ``RASTER_VISUAL_KINDS``    → Replicate raster (asset_type ``raster``; bytes persisted to cache),
  * ``icon`` / ``decorative``  → a tiny generated SVG icon (asset_type ``svg_icon``).

Cache-first: compute the content hash, return the cached :class:`VisualAsset` on a hit; otherwise
generate → sanitize → persist row (INSERT OR IGNORE) → write bytes/markup to the on-disk cache.

Resilience: any provider failure (LLM, Replicate, sanitize) degrades to a tiny inline placeholder SVG
so lesson/quiz generation never hard-fails on a single visual (SPEC §9). Video kinds (none exist in the
``VisualKind`` enum today) and any video request while ``settings.video_enabled`` is off also degrade to
the placeholder.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.constants import (
    PROMPT_VERSION,
    RASTER_VISUAL_KINDS,
    SVG_VISUAL_KINDS,
)
from ..models import VisualAsset
from ..schemas.enums import VisualKind
from ..schemas.generation import GenVisualSpec
from . import cache, claude_svg, replicate_raster

logger = logging.getLogger("app.visuals")

_ICON_KINDS = frozenset({VisualKind.ICON.value, VisualKind.DECORATIVE.value})
_PLACEHOLDER_MODEL = "placeholder"


def _placeholder_svg(alt: str) -> str:
    """A minimal, safe, sanitizer-passing placeholder figure (has a viewBox; no script/href)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 75" role="img" '
        'aria-label="placeholder">'
        '<rect width="100" height="75" rx="6" fill="#eef2f7"/>'
        '<circle cx="35" cy="32" r="9" fill="#c7d2e0"/>'
        '<path d="M20 60 L44 38 L60 54 L72 44 L84 60 Z" fill="#c7d2e0"/>'
        "</svg>"
    )


def _icon_svg(alt: str) -> str:
    """A tiny decorative star icon (placeholder until a richer icon set lands)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" role="img" '
        'aria-label="icon">'
        '<path d="M12 2 L15 9 L22 9 L16 14 L18 22 L12 17 L6 22 L8 14 L2 9 L9 9 Z" '
        'fill="#f6c453"/>'
        "</svg>"
    )


def _kind_value(spec: GenVisualSpec) -> str:
    return spec.visual_kind.value if isinstance(spec.visual_kind, VisualKind) else str(spec.visual_kind)


def _svg_request_text(spec: GenVisualSpec) -> str:
    """Stable textual representation of the SVG *request* (not the output) used for the cache key."""
    return " :: ".join(
        [
            _kind_value(spec),
            spec.svg_request or spec.alt_text or "",
            spec.alt_text or "",
        ]
    )


def _svg_hash(
    spec: GenVisualSpec, *, model: str, language: str, grade_band: str, params: dict
) -> str:
    """Cache key for an inline SVG computed from the request inputs (deterministic, pre-generation).

    Keying on the request — not the generated markup — means a second identical request is a cache hit
    and never calls the LLM (SPEC §9 cost guardrail)."""
    key_params = {**params, "language": language, "grade_band": grade_band}
    return cache.compute_hash(
        asset_type="svg",
        model_id=model,
        model_version=None,
        prompt=_svg_request_text(spec),
        params=key_params,
        seed=None,
        output_format="svg",
    )


async def _store_svg(
    db: AsyncSession,
    *,
    asset_hash: str,
    asset_type: str,
    svg: str,
    alt: str,
    caption: str | None,
    language: str,
    model: str,
    params: dict,
) -> VisualAsset:
    """Write to disk + persist an inline SVG asset (svg / svg_icon) under a precomputed hash."""
    data = svg.encode("utf-8")
    path = cache.write_bytes_atomic(asset_hash, data, "svg")
    return await cache.persist(
        db,
        asset_hash=asset_hash,
        fields={
            "asset_type": asset_type,
            "model": model,
            "model_version": None,
            "params_json": params,
            "prompt": (caption or alt or "")[:2000],
            "lang": language,
            "width": None,
            "height": None,
            "bytes": len(data),
            "mime": "image/svg+xml",
            "file_path": str(path),
            "svg_inline": svg,
        },
    )


async def _placeholder_asset(
    db: AsyncSession, spec: GenVisualSpec, *, language: str, asset_type: str = "svg", icon: bool = False
) -> VisualAsset:
    """Persist + return the degrade-gracefully placeholder asset (cached per request like any other)."""
    alt = spec.alt_text or "figure"
    svg = _icon_svg(alt) if icon else _placeholder_svg(alt)
    params = {"kind": _kind_value(spec), "placeholder": True, "icon": icon, "prompt_version": PROMPT_VERSION}
    asset_hash = _svg_hash(
        spec, model=_PLACEHOLDER_MODEL, language=language, grade_band="", params=params
    )
    existing = await cache.get_or_none(db, asset_hash)
    if existing is not None:
        return existing
    return await _store_svg(
        db,
        asset_hash=asset_hash,
        asset_type=asset_type,
        svg=svg,
        alt=alt,
        caption=spec.caption,
        language=language,
        model=_PLACEHOLDER_MODEL,
        params=params,
    )


async def _ensure_svg(db: AsyncSession, spec: GenVisualSpec, *, language: str, grade_band: str) -> VisualAsset:
    params = {"kind": _kind_value(spec), "prompt_version": PROMPT_VERSION}
    asset_hash = _svg_hash(
        spec, model=settings.model_id, language=language, grade_band=grade_band, params=params
    )

    # Cache-first: an identical request is a hit and never calls the LLM.
    existing = await cache.get_or_none(db, asset_hash)
    if existing is not None:
        return existing

    try:
        result = await claude_svg.generate_svg(spec, language=language, grade_band=grade_band)
    except Exception:  # provider/sanitize failure → never hard-fail generation
        logger.warning("Claude-SVG generation failed; using placeholder", exc_info=True)
        return await _placeholder_asset(db, spec, language=language)

    return await _store_svg(
        db,
        asset_hash=asset_hash,
        asset_type="svg",
        svg=result["svg"],
        alt=result["alt"],
        caption=result.get("caption"),
        language=language,
        model=settings.model_id,
        params=params,
    )


async def _ensure_icon(db: AsyncSession, spec: GenVisualSpec, *, language: str) -> VisualAsset:
    # Icons/decoratives are cheap, deterministic SVGs — no LLM call needed for v1.
    return await _placeholder_asset(db, spec, language=language, asset_type="svg_icon", icon=True)


async def _ensure_raster(db: AsyncSession, spec: GenVisualSpec, *, language: str, grade_band: str) -> VisualAsset:
    # Cache-first: compute the key from the deterministic prompt + model + params before any provider call.
    prompt = replicate_raster.build_prompt(spec, grade_band=grade_band)
    model = replicate_raster.select_model(spec)
    params = replicate_raster.build_input(spec, prompt)
    asset_hash = cache.compute_hash(
        asset_type="raster",
        model_id=model,
        model_version=None,
        prompt=prompt,
        params=params,
        seed=params.get("seed"),
        output_format=replicate_raster.OUTPUT_FORMAT,
    )

    existing = await cache.get_or_none(db, asset_hash)
    if existing is not None:
        return existing

    try:
        result = await replicate_raster.generate_raster(spec, grade_band=grade_band)
    except Exception:  # provider failure → degrade to placeholder SVG
        logger.warning("Replicate raster generation failed; using placeholder", exc_info=True)
        return await _placeholder_asset(db, spec, language=language)

    # Replicate URLs expire — persist bytes to disk immediately under the precomputed hash.
    ext = result.output_format
    path = cache.write_bytes_atomic(asset_hash, result.data, ext)
    return await cache.persist(
        db,
        asset_hash=asset_hash,
        fields={
            "asset_type": "raster",
            "model": result.model,
            "model_version": result.model_version,
            "params_json": result.params,
            "prompt": result.prompt[:2000],
            "lang": language,
            "width": result.width,
            "height": result.height,
            "bytes": len(result.data),
            "mime": result.mime,
            "file_path": str(path),
            "svg_inline": None,
        },
    )


async def ensure_visual(
    db: AsyncSession, spec: GenVisualSpec, *, language: str, grade_band: str
) -> VisualAsset:
    """Return a cached :class:`VisualAsset` for ``spec`` or generate, sanitize, persist and cache one.

    Routes by ``spec.visual_kind``. Never raises on a provider failure — degrades to a placeholder SVG."""
    kind = _kind_value(spec)
    try:
        if kind in _ICON_KINDS:
            return await _ensure_icon(db, spec, language=language)
        if kind in SVG_VISUAL_KINDS:
            return await _ensure_svg(db, spec, language=language, grade_band=grade_band)
        if kind in RASTER_VISUAL_KINDS:
            return await _ensure_raster(db, spec, language=language, grade_band=grade_band)
        # Unknown / video kind, or video disabled: degrade to a safe placeholder.
        logger.info("Unrouted visual_kind %r → placeholder (video_enabled=%s)", kind, settings.video_enabled)
        return await _placeholder_asset(db, spec, language=language)
    except Exception:  # last-resort guard so a single visual never breaks generation
        logger.error("ensure_visual fell through to placeholder for kind %r", kind, exc_info=True)
        return await _placeholder_asset(db, spec, language=language)
