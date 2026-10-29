"""Settings an admin can see — and a few they can change — while the app runs (admin → Settings).

Which value applies, highest first:

1. an admin change made on the Settings page (stored in ``app_settings``, re-applied at startup);
2. the server's environment / ``.env`` (e.g. ``SA_MODEL_ID``);
3. the app's own default (``core.config.Settings``).

A change applies at once: every model call, budget check and limit reads ``settings`` when it runs,
and the backend is a single process. Undoing a change returns to the value the process started with
(2, else 3). Only the models and the daily budget are editable, models from a fixed list this app
was evaluated with — a typo there would fail every lesson. API keys stay in ``.env``: they are only
ever reported as set / not set.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, settings
from ..core.constants import PROMPT_VERSION
from ..models import AdminUser, AppSetting, GenerationUsage
from ..schemas.admin import AdminConfigOut, ConfigItem, ModelUsageToday
from .cost_guard import spent_today_usd

logger = logging.getLogger("schoolautomaton.admin")

# Models this app has run and been evaluated with (backend/evals/model_migration, 2026-10-28): the
# current default first, then the one it replaced. Each has a price in core.pricing, so the daily
# budget counts its calls.
MAIN_MODELS = ("claude-opus-5-5", "claude-opus-4-8")
SANITIZER_MODELS = ("claude-haiku-5-5", "claude-haiku-4-5")
BUDGET_MAX_USD = 1000.0  # a typo guard; the environment can still set any amount


@dataclass(frozen=True)
class _Spec:
    key: str  # the Settings field (or "prompt_version", fixed in code)
    group: str
    kind: str
    editable: bool = False
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None


# In display order.
SPECS: tuple[_Spec, ...] = (
    _Spec("model_id", "models", "choice", editable=True, choices=MAIN_MODELS),
    _Spec("sanitizer_model_id", "models", "choice", editable=True, choices=SANITIZER_MODELS),
    _Spec("daily_budget_usd", "spending", "number", editable=True, min=0.0, max=BUDGET_MAX_USD),
    _Spec("rate_per_min", "limits", "integer"),
    _Spec("rate_per_day", "limits", "integer"),
    _Spec("rate_ip_multiplier", "limits", "integer"),
    _Spec("answer_rate_per_min", "limits", "integer"),
    _Spec("answer_llm_rate_per_min", "limits", "integer"),
    _Spec("profile_create_per_hour", "limits", "integer"),
    _Spec("resume_fail_limit", "limits", "integer"),
    _Spec("resume_fail_window_s", "limits", "integer"),
    _Spec("admin_login_fail_limit", "limits", "integer"),
    _Spec("llm_request_timeout_s", "limits", "number"),
    _Spec("visual_phase_budget_s", "limits", "number"),
    _Spec("per_visual_timeout_s", "limits", "number"),
    _Spec("anthropic_api_key", "keys", "status"),
    _Spec("replicate_api_token", "keys", "status"),
    _Spec("env", "about", "text"),
    _Spec("prompt_version", "about", "text"),
)
_BY_KEY = {s.key: s for s in SPECS}
EDITABLE_KEYS = frozenset(s.key for s in SPECS if s.editable)


class UnknownSetting(LookupError):
    pass


class NotEditable(ValueError):
    pass


class InvalidValue(ValueError):
    pass


@dataclass
class _State:
    # key -> (value, "env" | "default") as the process started, before any admin change.
    base: dict[str, tuple[Any, str]] = field(default_factory=dict)
    # Admin changes applied to ``settings`` right now (key -> value).
    applied: dict[str, Any] = field(default_factory=dict)


_state: _State | None = None


def _get_state() -> _State:
    """The start-up values, captured before the first admin change is applied (``model_fields_set``
    holds the fields the environment / .env provided; an assignment would add to it)."""
    global _state
    if _state is None:
        provided = settings.model_fields_set
        _state = _State(
            base={
                key: (getattr(settings, key), "env" if key in provided else "default")
                for key in EDITABLE_KEYS
            }
        )
    return _state


def validate(key: str, value: Any) -> Any:
    """The normalized value an admin may set for ``key``; raises otherwise."""
    spec = _BY_KEY.get(key)
    if spec is None:
        raise UnknownSetting(key)
    if not spec.editable:
        raise NotEditable(key)
    if spec.kind == "choice":
        if not isinstance(value, str) or value not in spec.choices:
            raise InvalidValue(f"{key} must be one of: {', '.join(spec.choices)}")
        return value
    # number
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidValue(f"{key} must be a number")
    lo = spec.min if spec.min is not None else -math.inf
    hi = spec.max if spec.max is not None else math.inf
    if not lo <= value <= hi:
        raise InvalidValue(f"{key} must be between {spec.min:g} and {spec.max:g}")
    return round(float(value), 2)


def _apply(key: str, value: Any) -> None:
    _get_state()  # capture the start-up values first
    setattr(settings, key, value)
    _get_state().applied[key] = value


def _restore(key: str) -> None:
    state = _get_state()
    setattr(settings, key, state.base[key][0])
    state.applied.pop(key, None)


async def load_overrides(db: AsyncSession) -> int:
    """Re-apply the admin changes stored in ``app_settings`` (at startup). A stored value this
    release no longer allows (e.g. a model taken off the list) is skipped with a warning — the
    environment / default applies instead. Returns how many were applied."""
    _get_state()
    rows = await db.scalars(select(AppSetting).where(AppSetting.key.in_(EDITABLE_KEYS)))
    applied = 0
    for row in rows:
        try:
            value = validate(row.key, row.value_json)
        except ValueError as exc:
            logger.warning("Ignoring the stored admin setting %s=%r: %s", row.key, row.value_json, exc)
            continue
        _apply(row.key, value)
        # A warning so it reaches the server log (info doesn't): it explains why .env isn't followed.
        logger.warning("Admin setting in effect (wins over .env): %s=%r", row.key, value)
        applied += 1
    return applied


async def set_override(db: AsyncSession, key: str, value: Any, admin: AdminUser) -> ConfigItem:
    """Store an admin change, then apply it (only once it is committed, so a failed save never
    leaves the app running on a value that isn't stored)."""
    value = validate(key, value)
    row = await db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value_json=value, is_secret=False, updated_by=admin.id)
        db.add(row)
    else:
        row.value_json = value
        row.is_secret = False
        row.updated_by = admin.id
        row.updated_at = datetime.now(UTC)
    await db.commit()
    before = getattr(settings, key)
    _apply(key, value)
    logger.warning("Admin %s changed %s: %r -> %r", admin.username, key, before, value)
    return (await _items(db, only=key))[0]


async def clear_override(db: AsyncSession, key: str, admin: AdminUser) -> ConfigItem:
    """Undo an admin change: back to the environment's value, else the app default."""
    spec = _BY_KEY.get(key)
    if spec is None:
        raise UnknownSetting(key)
    if not spec.editable:
        raise NotEditable(key)
    row = await db.get(AppSetting, key)
    if row is not None:
        await db.delete(row)
        await db.commit()
    before = getattr(settings, key)
    _restore(key)
    if before != getattr(settings, key):
        logger.warning(
            "Admin %s undid the change to %s: %r -> %r", admin.username, key, before, getattr(settings, key)
        )
    return (await _items(db, only=key))[0]


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back without a zone; they are stored in UTC."""
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _default(key: str) -> Any:
    info = Settings.model_fields.get(key)
    return None if info is None else info.default


async def _items(db: AsyncSession, *, only: str | None = None) -> list[ConfigItem]:
    state = _get_state()
    provided = settings.model_fields_set
    rows = {
        r.key: r
        for r in await db.scalars(select(AppSetting).where(AppSetting.key.in_(EDITABLE_KEYS)))
    }
    editor_ids = {r.updated_by for r in rows.values() if r.updated_by is not None}
    usernames = (
        {a.id: a.username for a in await db.scalars(select(AdminUser).where(AdminUser.id.in_(editor_ids)))}
        if editor_ids
        else {}
    )

    items: list[ConfigItem] = []
    for spec in SPECS:
        if only is not None and spec.key != only:
            continue
        info = Settings.model_fields.get(spec.key)
        env_name = info.alias if info is not None else None
        if spec.key == "prompt_version":
            items.append(ConfigItem(key=spec.key, group=spec.group, kind=spec.kind,
                                    value=PROMPT_VERSION, source="code"))
            continue
        current = getattr(settings, spec.key)
        if spec.kind == "status":  # a key: only whether it is set — never the value
            items.append(ConfigItem(key=spec.key, group=spec.group, kind=spec.kind,
                                    value=bool(current), source="env" if current else "default",
                                    env_name=env_name))
            continue
        if not spec.editable:
            items.append(ConfigItem(key=spec.key, group=spec.group, kind=spec.kind, value=current,
                                    source="env" if spec.key in provided else "default",
                                    env_name=env_name, default_value=_default(spec.key)))
            continue
        base_value, base_source = state.base[spec.key]
        by_admin = spec.key in state.applied
        row = rows.get(spec.key) if by_admin else None
        items.append(ConfigItem(
            key=spec.key, group=spec.group, kind=spec.kind, value=current,
            source="admin" if by_admin else base_source, env_name=env_name, editable=True,
            base_value=base_value, base_source=base_source, default_value=_default(spec.key),
            choices=list(spec.choices), min=spec.min, max=spec.max,
            updated_at=_aware(row.updated_at) if row is not None else None,
            updated_by=usernames.get(row.updated_by) if row is not None else None,
        ))
    return items


async def usage_today(db: AsyncSession, now: datetime | None = None) -> list[ModelUsageToday]:
    """AI calls since 00:00 UTC per provider/model — shows which model is really answering."""
    start = _day_start(now)
    rows = await db.execute(
        select(
            GenerationUsage.provider,
            GenerationUsage.model,
            func.count(),
            func.sum(GenerationUsage.est_cost_usd),
            func.max(GenerationUsage.created_at),
        )
        .where(GenerationUsage.created_at >= start)
        .group_by(GenerationUsage.provider, GenerationUsage.model)
    )
    out = [
        ModelUsageToday(
            provider=provider, model=model, calls=int(calls),
            cost_usd=round(float(cost), 4) if cost is not None else None,
            last_call_at=_aware(last),
        )
        for provider, model, calls, cost, last in rows.all()
    ]
    out.sort(key=lambda u: (-(u.cost_usd or 0.0), -u.calls, u.model))
    return out


def _day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


async def config_for_admin(db: AsyncSession, *, can_edit: bool) -> AdminConfigOut:
    now = datetime.now(UTC)
    return AdminConfigOut(
        can_edit=can_edit,
        items=await _items(db),
        usage_today=await usage_today(db, now),
        spent_today_usd=round(await spent_today_usd(db, now), 4),
        budget_usd=float(settings.daily_budget_usd or 0.0),
        day_started_at=_day_start(now),
    )


def reset_for_tests() -> None:
    """Undo every applied admin change in memory (tests share one ``settings`` object)."""
    if _state is None:
        return
    for key in list(_state.applied):
        _restore(key)
