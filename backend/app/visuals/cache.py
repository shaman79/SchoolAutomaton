"""Content-addressed cache for visual assets.

The cache key is a sha256 of a canonical JSON document so that semantically identical generation
requests collapse to one stored asset (SPEC visual_pipeline / §9 cost guardrails). The key inputs:

    {asset_type, model_id, model_version, normalized_prompt, params (sorted), seed, output_format}

``normalized_prompt`` is NFC-normalised, lower-cased and whitespace-collapsed so trivial textual
differences do not bust the cache. Bytes are written to disk under a two-level sharded directory and
the :class:`~app.models.VisualAsset` row is persisted with INSERT-OR-IGNORE semantics (SQLite is a
single writer; concurrent generators may race on the same hash).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.base import utcnow
from ..models import VisualAsset


def normalize_prompt(text: str | None) -> str:
    """NFC-normalise, lower-case and collapse runs of whitespace to single spaces."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text).lower()
    return " ".join(normalized.split())


def compute_hash(
    *,
    asset_type: str,
    model_id: str,
    model_version: str | None,
    prompt: str | None,
    params: dict[str, Any] | None,
    seed: int | None,
    output_format: str,
) -> str:
    """Return the sha256 content-hash key for a visual asset request.

    The document is serialised with ``sort_keys=True`` and a stable separator so the digest is
    deterministic regardless of dict insertion order or whitespace in the source prompt.
    """
    document = {
        "asset_type": asset_type,
        "model_id": model_id,
        "model_version": model_version,
        "normalized_prompt": normalize_prompt(prompt),
        "params": params or {},
        "seed": seed,
        "output_format": output_format,
    }
    canonical = json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_path(asset_hash: str, ext: str) -> Path:
    """Sharded on-disk path ``<cache_dir>/<h0:2>/<h2:4>/<hash>.<ext>``."""
    ext = ext.lstrip(".")
    return settings.visual_cache_dir / asset_hash[0:2] / asset_hash[2:4] / f"{asset_hash}.{ext}"


def write_bytes_atomic(asset_hash: str, data: bytes, ext: str) -> Path:
    """Write ``data`` to the sharded cache path atomically (temp file + ``os.replace``).

    Returns the final path. The temp file is created in the same directory so ``os.replace`` stays on
    one filesystem and is therefore atomic. Concurrent writers of the same content are harmless: the
    last replace wins and the bytes are identical anyway.
    """
    dest = cache_path(asset_hash, ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{asset_hash}-", suffix=f".{ext.lstrip('.')}.tmp", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, dest)
    except BaseException:
        # Best-effort cleanup of the temp file if the replace never happened.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return dest


async def get_or_none(db: AsyncSession, asset_hash: str) -> VisualAsset | None:
    """Return the cached :class:`VisualAsset` for ``asset_hash`` or ``None``.

    On a hit, ``hit_count`` and ``last_accessed_at`` are bumped (best-effort LRU bookkeeping).
    """
    asset = await db.get(VisualAsset, asset_hash)
    if asset is None:
        return None
    asset.hit_count = (asset.hit_count or 0) + 1
    asset.last_accessed_at = utcnow()
    return asset


async def persist(db: AsyncSession, *, asset_hash: str, fields: dict[str, Any]) -> VisualAsset:
    """Persist a :class:`VisualAsset` with INSERT-OR-IGNORE semantics, then return the live row.

    Uses SQLite's ``INSERT ... ON CONFLICT DO NOTHING`` on the hash primary key so two generators that
    raced to produce the same content do not raise an ``IntegrityError`` — the first writer wins and
    both callers receive the persisted row.
    """
    values = {"hash": asset_hash, **fields}
    stmt = sqlite_insert(VisualAsset).values(**values).on_conflict_do_nothing(index_elements=["hash"])
    await db.execute(stmt)
    await db.flush()

    asset = await db.get(VisualAsset, asset_hash)
    if asset is None:  # pragma: no cover - defensive; the insert guarantees a row exists
        asset = VisualAsset(hash=asset_hash, **fields)
        db.add(asset)
        await db.flush()
    return asset


async def touch_hit(db: AsyncSession, asset_hash: str) -> None:
    """Increment ``hit_count`` / refresh ``last_accessed_at`` without loading the row into the session."""
    await db.execute(
        update(VisualAsset)
        .where(VisualAsset.hash == asset_hash)
        .values(hit_count=VisualAsset.hit_count + 1, last_accessed_at=utcnow())
    )
