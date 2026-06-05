"""First-boot bootstrap: create the admin from env if none exists, and seed badge definitions from
``app/data/badges.yaml`` (provided by the B4 agent; a no-op until the file exists)."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.security import hash_password
from ..models import AdminUser, BadgeDefinition

_BADGES_YAML = Path(__file__).resolve().parent.parent / "data" / "badges.yaml"


async def bootstrap_admin(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(AdminUser))
    if count:
        return
    db.add(
        AdminUser(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role="admin",
        )
    )


def _as_i18n(value) -> dict:
    if isinstance(value, dict):
        return value
    return {"en": str(value)}


async def seed_badges(db: AsyncSession) -> None:
    if not _BADGES_YAML.is_file():
        return
    data = yaml.safe_load(_BADGES_YAML.read_text(encoding="utf-8")) or []
    entries = data.get("badges", data) if isinstance(data, dict) else data
    for entry in entries:
        code = entry.get("code")
        if not code:
            continue
        existing = await db.scalar(select(BadgeDefinition).where(BadgeDefinition.code == code))
        title = _as_i18n(entry.get("title_i18n") or entry.get("title") or code)
        desc = _as_i18n(entry.get("description_i18n") or entry.get("description") or "")
        if existing is None:
            db.add(
                BadgeDefinition(
                    code=code,
                    title_i18n_json=title,
                    description_i18n_json=desc,
                    icon_asset_hash=entry.get("icon_asset_hash"),
                    criterion_key=entry.get("criterion_key", code),
                    criterion_params_json=entry.get("criterion_params"),
                    tiered=bool(entry.get("tiered", False)),
                )
            )
        else:
            existing.title_i18n_json = title
            existing.description_i18n_json = desc
            existing.criterion_key = entry.get("criterion_key", existing.criterion_key)
            existing.criterion_params_json = entry.get("criterion_params")
            existing.tiered = bool(entry.get("tiered", existing.tiered))


async def bootstrap(db: AsyncSession) -> None:
    await bootstrap_admin(db)
    await seed_badges(db)
