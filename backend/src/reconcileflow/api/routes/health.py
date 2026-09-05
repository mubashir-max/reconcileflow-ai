"""Liveness and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import APISettings
from ..dependencies import get_settings
from ..schemas import HealthResponse


router = APIRouter(prefix="/health", tags=["health"])
SettingsDependency = Annotated[APISettings, Depends(get_settings)]


@router.get("/live", response_model=HealthResponse, summary="Check process liveness")
def liveness(settings: SettingsDependency) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get("/ready", response_model=HealthResponse, summary="Check application readiness")
def readiness(settings: SettingsDependency) -> HealthResponse:
    # Settings have already been parsed and validated before the app is created.
    return HealthResponse(
        status="ready",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
