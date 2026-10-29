"""Admin realm: JWT login + dashboard/audit/runtime settings/content. Separate auth from learner profiles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.config import settings as cfg
from ....core.security import create_admin_token, verify_password_off_loop
from ....core.throttle import admin_login_throttle
from ....models import (
    AdminUser,
    GenerationUsage,
    LearningRequest,
    Lesson,
    Profile,
    Quiz,
    SanitizationAudit,
)
from ....schemas.admin import (
    AdminConfigOut,
    AdminLoginIn,
    AuditRecord,
    ConfigItem,
    ConfigUpdateIn,
    ContentRecord,
    DashboardOut,
    TokenOut,
)
from ....schemas.common import Page
from ....services import runtime_settings
from ...deps import client_ip_hash, get_current_admin, get_db

router = APIRouter(prefix="/admin", tags=["admin"])


def _utc(dt: datetime) -> datetime:
    """SQLite hands datetimes back without a zone; they are stored in UTC. Sent without one, the
    browser would read them as its own local time (an hour off in Prague)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


@router.post("/auth/login", response_model=TokenOut)
async def login(body: AdminLoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    # Throttled per client IP and per username (escalating lockout → 429 + Retry-After). The attempt
    # is counted up front and forgiven on success, so parallel guesses can't all slip through.
    keys = [f"ip:{client_ip_hash(request)}", f"user:{body.username.strip().casefold()}"]
    admin_login_throttle.begin(keys)
    admin = await db.scalar(select(AdminUser).where(AdminUser.username == body.username))
    # Argon2 runs in a worker thread (it would stall the event loop), and an unknown username is
    # checked against a dummy hash so it answers no faster than a real one.
    ok = await verify_password_off_loop(
        body.password, admin.password_hash if admin is not None else None
    )
    if admin is None or not admin.is_active or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    admin_login_throttle.succeeded(keys)
    admin.last_login_at = datetime.now(UTC)
    token = create_admin_token(subject=admin.username, role=admin.role)
    return TokenOut(access_token=token, expires_in=cfg.jwt_expire_minutes * 60)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(_: AdminUser = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    since = datetime.now(UTC) - timedelta(hours=24)

    requests_24h = await db.scalar(
        select(func.count()).select_from(LearningRequest).where(LearningRequest.created_at >= since)
    )
    decision_rows = (
        await db.execute(
            select(SanitizationAudit.decision_type, func.count()).group_by(
                SanitizationAudit.decision_type
            )
        )
    ).all()
    decisions = {dt: int(n) for dt, n in decision_rows}

    anthropic_cost = await db.scalar(
        select(func.coalesce(func.sum(GenerationUsage.est_cost_usd), 0.0)).where(
            GenerationUsage.provider == "anthropic"
        )
    )
    replicate_cost = await db.scalar(
        select(func.coalesce(func.sum(GenerationUsage.est_cost_usd), 0.0)).where(
            GenerationUsage.provider == "replicate"
        )
    )
    cache_read = await db.scalar(
        select(func.coalesce(func.sum(GenerationUsage.cache_read_tokens), 0))
    )
    cache_create = await db.scalar(
        select(func.coalesce(func.sum(GenerationUsage.cache_creation_tokens), 0))
    )
    denom = int(cache_read or 0) + int(cache_create or 0)
    cache_hit_rate = (int(cache_read or 0) / denom) if denom else 0.0

    injection_attempts = await db.scalar(
        select(func.count()).select_from(SanitizationAudit).where(
            SanitizationAudit.injection_detected.is_(True)
        )
    )

    return DashboardOut(
        requests_24h=int(requests_24h or 0),
        decisions_breakdown=decisions,
        anthropic_cost_usd=round(float(anthropic_cost or 0.0), 4),
        replicate_cost_usd=round(float(replicate_cost or 0.0), 4),
        cache_hit_rate=round(cache_hit_rate, 4),
        crisis_events=decisions.get("crisis", 0),
        refusals=decisions.get("refuse", 0),
        injection_attempts=int(injection_attempts or 0),
        profiles_total=int(await db.scalar(select(func.count()).select_from(Profile)) or 0),
        lessons_total=int(await db.scalar(select(func.count()).select_from(Lesson)) or 0),
        quizzes_total=int(await db.scalar(select(func.count()).select_from(Quiz)) or 0),
    )


@router.get("/audit", response_model=Page[AuditRecord])
async def audit(
    decision_type: str | None = Query(default=None),
    injection_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SanitizationAudit)
    if decision_type:
        stmt = stmt.where(SanitizationAudit.decision_type == decision_type)
    if injection_only:
        stmt = stmt.where(SanitizationAudit.injection_detected.is_(True))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(SanitizationAudit.ts.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    items = [
        AuditRecord(
            id=r.id,
            request_id=r.request_id,
            ts=_utc(r.ts),
            decision_type=r.decision_type,
            language=r.language,
            suspicion_score=r.suspicion_score,
            injection_detected=r.injection_detected,
            safety_flags=r.safety_flags,
            reason=r.reason,
            raw_length=r.raw_length,
            topic_hash=(r.classifier_verdict_json or {}).get("topic_sha256"),
        )
        for r in rows
    ]
    return Page[AuditRecord](items=items, total=int(total or 0), page=page, page_size=page_size)


@router.get("/config", response_model=AdminConfigOut)
async def get_config(admin: AdminUser = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """The settings the backend runs with now, where each comes from, and today's AI use per model."""
    return await runtime_settings.config_for_admin(db, can_edit=admin.role == "admin")


def _config_error(exc: Exception) -> HTTPException:
    if isinstance(exc, runtime_settings.UnknownSetting):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Unknown setting")
    if isinstance(exc, runtime_settings.NotEditable):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "This setting can only be changed on the server")
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.put("/config/{key}", response_model=ConfigItem)
async def put_config(
    key: str,
    body: ConfigUpdateIn,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change an editable setting (models, daily budget). Applies at once and survives restarts."""
    if admin.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Read-only role")
    try:
        return await runtime_settings.set_override(db, key, body.value, admin)
    except (LookupError, ValueError) as exc:
        raise _config_error(exc) from exc


@router.delete("/config/{key}", response_model=ConfigItem)
async def delete_config(
    key: str,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Undo an admin change: back to the server environment's value, else the app default."""
    if admin.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Read-only role")
    try:
        return await runtime_settings.clear_override(db, key, admin)
    except (LookupError, ValueError) as exc:
        raise _config_error(exc) from exc


@router.get("/content", response_model=list[ContentRecord])
async def content(
    subject: str | None = Query(default=None),
    grade_band: str | None = Query(default=None),
    _: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    lesson_stmt = select(Lesson)
    quiz_stmt = select(Quiz)
    if subject:
        lesson_stmt = lesson_stmt.where(Lesson.subject == subject)
        quiz_stmt = quiz_stmt.where(Quiz.subject == subject)
    if grade_band:
        lesson_stmt = lesson_stmt.where(Lesson.grade_band == grade_band)
        quiz_stmt = quiz_stmt.where(Quiz.grade_band == grade_band)
    lessons = (await db.execute(lesson_stmt.order_by(Lesson.created_at.desc()).limit(100))).scalars().all()
    quizzes = (await db.execute(quiz_stmt.order_by(Quiz.created_at.desc()).limit(100))).scalars().all()
    out = [
        ContentRecord(
            id=lz.id, kind="lesson", topic=lz.topic, grade_band=lz.grade_band,
            language=lz.detected_language, cache_key=lz.content_cache_key, created_at=_utc(lz.created_at),
        )
        for lz in lessons
    ] + [
        ContentRecord(
            id=q.id, kind="quiz", topic=q.title, grade_band=q.grade_band,
            language=q.language, cache_key=None, created_at=_utc(q.created_at),
        )
        for q in quizzes
    ]
    out.sort(key=lambda r: r.created_at, reverse=True)
    return out
