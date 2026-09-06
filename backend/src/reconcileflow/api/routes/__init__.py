"""Versioned API route collection."""

from fastapi import APIRouter

from .health import router as health_router
from .files import router as files_router
from .runs import router as runs_router
from .execution import router as execution_router
from .auth import router as auth_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(files_router)
api_router.include_router(runs_router)
api_router.include_router(execution_router)
api_router.include_router(auth_router)

__all__ = ["api_router"]
