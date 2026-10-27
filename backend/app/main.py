"""FastAPI application entrypoint.

Lifespan: ensure data dirs, create tables (dev), bootstrap admin + seed badges. Middleware: CORS +
security headers (strict CSP in production, relaxed for /docs in dev). NotImplementedError → 501 so
not-yet-built module stubs degrade cleanly during parallel implementation."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from .api.v1.router import api_router
from .core.config import settings
from .core.tasks import task_registry
from .db.bootstrap import bootstrap
from .db.session import SessionLocal, init_db
from .models import LearningRequest, SectionVisual

logger = logging.getLogger("schoolautomaton")


async def _reap_stuck_requests(db: AsyncSession) -> None:
    """Fail any request still 'queued'/'generating' at boot. Generation runs as an in-process
    background task with an in-memory progress broker — neither survives a restart, so such a row is
    orphaned: its loading screen would hang forever. Marking it 'error' lets the SSE/poll fast-path
    report failure so the learner can retry."""
    result = await db.execute(
        update(LearningRequest)
        .where(LearningRequest.status.in_(("queued", "generating")))
        .values(
            status="error",
            error_code="failed",
            error_message="Generation was interrupted by a server restart. Please try again.",
        )
    )
    if result.rowcount:
        logger.warning("Reaped %s stuck generation request(s) on startup", result.rowcount)


async def _reap_stuck_visuals(db: AsyncSession) -> None:
    """Fail any section visual still 'pending'/'generating' at boot. Visual realization is an
    in-process background task that doesn't survive a restart, so such a row would never finish and
    the reader would poll its placeholder forever. Marking it 'failed' lets the client fall back to
    the alt text."""
    result = await db.execute(
        update(SectionVisual)
        .where(SectionVisual.status.in_(("pending", "generating")))
        .values(status="failed")
    )
    if result.rowcount:
        logger.warning("Reaped %s stuck section visual(s) on startup", result.rowcount)

_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_CSP_PROD = (
    "default-src 'self'; "
    "img-src 'self' data: https://replicate.delivery https://*.replicate.com; "
    "media-src 'self' https://replicate.delivery; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    async with SessionLocal() as db:
        await bootstrap(db)
        await _reap_stuck_requests(db)
        await _reap_stuck_visuals(db)
        await db.commit()
    logger.info("SchoolAutomaton backend ready (env=%s)", settings.env)
    yield


# The interactive docs + schema stay a development aid: in production they'd hand anyone a map of
# every endpoint (the frontend's types are generated from a dev server).
_docs = {} if not settings.is_production else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(
    title="SchoolAutomaton API",
    version="0.1.0",
    description="Sanitize a student prompt, generate study materials or an interactive test, gamify.",
    lifespan=lifespan,
    **_docs,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if settings.is_production and not request.url.path.startswith(_DOCS_PATHS):
        response.headers.setdefault("Content-Security-Policy", _CSP_PROD)
    return response


@app.exception_handler(NotImplementedError)
async def _not_implemented(request: Request, exc: NotImplementedError):
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"detail": str(exc) or "Not implemented yet", "code": "not_implemented"},
    )


@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok", "app": settings.app_name, "env": settings.env}


@app.get("/api/v1/health", tags=["meta"])
async def health():
    """Liveness + readiness for the deploy script: the database answers, and how much work a restart
    would cut off right now (lessons/quizzes being generated, lesson parts being written) — the
    update script waits for that to reach 0 before restarting."""
    try:
        async with SessionLocal() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=5)
    except Exception:  # noqa: BLE001 — any failure means "not ready"
        logger.exception("Health check: database unreachable")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "db": "error", "active_generations": task_registry.active_count()},
        )
    return {"status": "ok", "db": "ok", "active_generations": task_registry.active_count()}


app.include_router(api_router)
