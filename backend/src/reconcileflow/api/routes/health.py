"""Liveness and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError

from reconcileflow.persistence.dependencies import DatabaseDependency

from ..config import APISettings
from ..dependencies import get_settings
from ..errors import APIError
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
def readiness(settings: SettingsDependency, database: DatabaseDependency) -> HealthResponse:
    try:
        database.check_connection()
    except SQLAlchemyError as error:
        raise APIError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="The service is not ready.",
        ) from error
    return HealthResponse(
        status="ready",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
