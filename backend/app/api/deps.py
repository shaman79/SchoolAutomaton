"""FastAPI dependencies — two separate auth realms + request fingerprinting.

Learner: ``X-Resume-Code`` header → Profile (we look up by sha256 hash). Admin: ``Authorization:
Bearer <jwt>``. The client IP/device is hashed (salted) for rate-limiting and audit, never stored raw."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import decode_admin_token, hash_resume_code, salted_hash
from ..db.session import get_db
from ..models import AdminUser, Profile


@dataclass
class RequestContext:
    """Per-request fingerprint passed to the sanitization pipeline (Layer 0/5)."""

    ip_hash: str
    user_agent: str
    profile_id: int | None


async def get_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    return db


def get_client_ip(request: Request) -> str:
    """Best-effort client IP, honouring a single reverse proxy (nginx) X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_profile(
    db: AsyncSession = Depends(get_db),
    x_resume_code: str | None = Header(default=None, alias="X-Resume-Code"),
) -> Profile:
    if not x_resume_code:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Resume-Code")
    profile = await db.scalar(
        select(Profile).where(Profile.resume_code_hash == hash_resume_code(x_resume_code))
    )
    if profile is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown resume code")
    return profile


async def get_optional_profile(
    db: AsyncSession = Depends(get_db),
    x_resume_code: str | None = Header(default=None, alias="X-Resume-Code"),
) -> Profile | None:
    if not x_resume_code:
        return None
    return await db.scalar(
        select(Profile).where(Profile.resume_code_hash == hash_resume_code(x_resume_code))
    )


async def get_request_context(
    request: Request,
    profile: Profile | None = Depends(get_optional_profile),
) -> RequestContext:
    return RequestContext(
        ip_hash=salted_hash(get_client_ip(request)),
        user_agent=request.headers.get("user-agent", "")[:200],
        profile_id=profile.id if profile else None,
    )


async def get_current_admin(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> AdminUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_admin_token(token)
    except jwt.PyJWTError as exc:  # expired / invalid
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    admin = await db.scalar(select(AdminUser).where(AdminUser.username == payload.get("sub")))
    if admin is None or not admin.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin not found or inactive")
    return admin
