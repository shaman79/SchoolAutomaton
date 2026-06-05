"""FastAPI application entrypoint.

Lifespan: ensure data dirs, create tables (dev), bootstrap admin + seed badges. Middleware: CORS +
security headers (strict CSP in production, relaxed for /docs in dev). NotImplementedError → 501 so
not-yet-built module stubs degrade cleanly during parallel implementation."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.v1.router import api_router
from .core.config import settings
from .db.bootstrap import bootstrap
from .db.session import SessionLocal, init_db

logger = logging.getLogger("schoolautomaton")

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
        await db.commit()
    logger.info("SchoolAutomaton backend ready (env=%s)", settings.env)
    yield


app = FastAPI(
    title="SchoolAutomaton API",
    version="0.1.0",
    description="Sanitize a student prompt, generate study materials or an interactive test, gamify.",
    lifespan=lifespan,
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


app.include_router(api_router)
