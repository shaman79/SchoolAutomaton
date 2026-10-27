"""FastAPI dependencies — two separate auth realms + request fingerprinting.

Learner: ``X-Resume-Code`` header → Profile (we look up by sha256 hash; failed lookups are throttled
per client IP against guessing). Admin: ``Authorization: Bearer <jwt>``. The client IP/device is
hashed (salted) for rate-limiting and audit, never stored raw."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import decode_admin_token, hash_resume_code, salted_hash
from ..core.throttle import resume_guard
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
    """Best-effort real client IP. Behind Cloudflare the true visitor IP is in CF-Connecting-IP
    (X-Forwarded-For would otherwise collapse many users onto a Cloudflare edge IP and blur
    per-user rate limits). Falls back to X-Forwarded-For (nginx) then the socket peer."""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def client_ip_hash(request: Request) -> str:
    """The salted hash of the client IP — the only form in which an IP is ever kept or keyed on."""
    return salted_hash(get_client_ip(request))


async def lookup_profile_by_code(db: AsyncSession, request: Request, code: str) -> Profile | None:
    """Resolve a resume code to its Profile, throttling GUESSING per client IP.

    Every resume-code lookup goes through here. Valid codes are never slowed; distinct unknown codes
    are counted per IP, and past ``settings.resume_fail_limit`` per window a NEW code from that IP
    gets 429 without being looked up (see ``core.throttle.ResumeCodeGuard``)."""
    ip = client_ip_hash(request)
    code_hash = hash_resume_code(code)
    resume_guard.before_lookup(ip, code_hash)
    profile = await db.scalar(select(Profile).where(Profile.resume_code_hash == code_hash))
    resume_guard.after_lookup(ip, code_hash, found=profile is not None)
    return profile


async def get_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_resume_code: str | None = Header(default=None, alias="X-Resume-Code"),
) -> Profile:
    if not x_resume_code:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Resume-Code")
    profile = await lookup_profile_by_code(db, request, x_resume_code)
    if profile is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown resume code")
    return profile


async def get_optional_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_resume_code: str | None = Header(default=None, alias="X-Resume-Code"),
) -> Profile | None:
    if not x_resume_code:
        return None
    return await lookup_profile_by_code(db, request, x_resume_code)


async def get_request_context(
    request: Request,
    profile: Profile | None = Depends(get_optional_profile),
) -> RequestContext:
    return RequestContext(
        ip_hash=client_ip_hash(request),
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
