"""Content-addressed visual cache (SVG / raster / icon / video) + cost telemetry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, utcnow


class VisualAsset(Base):
    """Keyed by sha256 of canonical JSON {asset_type, model_id, model_version, normalized_prompt,
    sorted params, seed, output_format}. INSERT OR IGNORE on the hash PK (single-writer SQLite)."""

    __tablename__ = "visual_assets"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(12))  # svg|raster|svg_icon|video
    model: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    params_json: Mapped[dict] = mapped_column(JSON)
    prompt: Mapped[str] = mapped_column(Text)  # rewritten kid-safe prompt; never raw student text
    lang: Mapped[str | None] = mapped_column(String(12), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str] = mapped_column(String(40))
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    svg_inline: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized SVG markup
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
