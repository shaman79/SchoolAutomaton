"""Serve cached visual assets by content hash with immutable caching."""

from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import VisualAsset
from ...deps import get_db

router = APIRouter(prefix="/assets", tags=["assets"])

_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/{asset_hash}")
async def get_asset(asset_hash: str, db: AsyncSession = Depends(get_db)):
    asset = await db.get(VisualAsset, asset_hash)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")

    asset.hit_count = (asset.hit_count or 0) + 1  # best-effort LRU bookkeeping

    if asset.asset_type == "svg" and asset.svg_inline:
        return Response(content=asset.svg_inline, media_type="image/svg+xml", headers=_IMMUTABLE)

    if asset.file_path and await anyio.to_thread.run_sync(Path(asset.file_path).is_file):
        return FileResponse(asset.file_path, media_type=asset.mime, headers=_IMMUTABLE)

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset payload unavailable")
