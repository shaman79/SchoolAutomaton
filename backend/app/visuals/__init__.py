"""Hybrid visual pipeline (SPEC visual_pipeline). Implemented by the **B3 agent**:
``router.py`` (SVG vs Replicate-raster vs video routing by visual_kind/layout_slot),
``claude_svg.py``, ``replicate_raster.py``, ``svg_sanitize.py`` (lxml: strip script/foreignObject/
external href/on*, require viewBox, cap ~60KB), ``cache.py`` (content-hash disk cache + atomic write +
INSERT OR IGNORE). Prompts to Replicate are kid-safe rewrites — never raw student text."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import VisualAsset
from ..schemas.generation import GenVisualSpec


async def ensure_visual(
    db: AsyncSession, spec: GenVisualSpec, *, language: str, grade_band: str
) -> VisualAsset:
    """Return a cached VisualAsset for ``spec`` (hash hit) or generate, sanitize, persist, and cache
    it. Routes SVG kinds to Claude-SVG and raster kinds to Replicate per LAYOUT_SLOT_SPECS.

    Implemented by the B3 visual-pipeline module; the body lives in :mod:`app.visuals.router`."""
    from .router import ensure_visual as _ensure_visual

    return await _ensure_visual(db, spec, language=language, grade_band=grade_band)
