"""Aggregate all v1 routers under ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from .routes import (
    admin,
    answers,
    assets,
    lessons,
    profiles,
    quizzes,
    requests,
    review,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(profiles.router)
api_router.include_router(requests.router)
api_router.include_router(lessons.router)
api_router.include_router(quizzes.router)
api_router.include_router(answers.router)
api_router.include_router(review.router)
api_router.include_router(assets.router)
api_router.include_router(admin.router)
