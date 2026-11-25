"""FastAPI dependencies — two separate auth realms + request fingerprinting.

Learner: ``X-Resume-Code`` header → Profile (we look up by sha256 hash; failed lookups are throttled
per client IP against guessing). Parent: ``X-Parent-Code`` header → the learner it follows, read-only
plus giving tasks (same hashing and the same guessing throttle). Admin: ``Authorization: Bearer <jwt>``. The client IP/device is
hashed (salted) for rate-limiting and audit, never stored raw."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import decode_admin_token, hash_parent_code, hash_resume_code, salted_hash
from ..core.throttle import resume_guard
from ..db.session import get_db
from ..models import AdminUser, ParentLink, Profile


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


# Longest parent code worth looking up (10 characters plus separators); anything longer is unknown.
_MAX_PARENT_CODE = 32


@dataclass
class ParentAccess:
    """A parent following one learner: the link (their parent code) and that learner's profile."""

    link: ParentLink
    child: Profile


async def lookup_parent_link(db: AsyncSession, request: Request, code: str) -> ParentLink | None:
    """Resolve a parent code, throttled exactly like resume codes — the same per-IP budget of
    unknown codes covers both, so guessing can't switch to the other kind to get more tries."""
    ip = client_ip_hash(request)
    code_hash = hash_parent_code(code[:_MAX_PARENT_CODE])
    resume_guard.before_lookup(ip, code_hash)
    link = await db.scalar(select(ParentLink).where(ParentLink.code_hash == code_hash))
    resume_guard.after_lookup(ip, code_hash, found=link is not None)
    return link


async def get_parent_access(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_parent_code: str | None = Header(default=None, alias="X-Parent-Code"),
) -> ParentAccess:
    if not x_parent_code:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Parent-Code")
    link = await lookup_parent_link(db, request, x_parent_code)
    child = await db.get(Profile, link.profile_id) if link is not None else None
    if link is None or child is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown parent code")
    return ParentAccess(link=link, child=child)


def get_session_key(
    x_learning_session: str | None = Header(default=None, alias="X-Learning-Session"),
) -> str | None:
    """The learning session (request id) the client is in, sent with lesson/quiz calls; it is what
    opens shared content (see services.content_access). Malformed values count as absent."""
    from ..services.content_access import session_key

    return session_key(x_learning_session)


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
