"""Liveness and readiness endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.exc import SQLAlchemyError

from reconcileflow.persistence.dependencies import DatabaseDependency
from reconcileflow.persistence import PersistenceUnitOfWork

from ..config import APISettings
from ..dependencies import get_settings
from ..errors import APIError
from ..schemas import HealthResponse, WorkerHealthResponse


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


@router.get(
    "/worker-ready",
    response_model=WorkerHealthResponse,
    summary="Check aggregate worker readiness",
)
def worker_readiness(
    response: Response,
    settings: SettingsDependency,
    database: DatabaseDependency,
) -> WorkerHealthResponse:
    with database.session() as session:
        active, stale = PersistenceUnitOfWork(session).workers.health_counts(
            stale_before=datetime.now(UTC) - timedelta(
                seconds=settings.worker_health_stale_seconds
            )
        )
    if active == 0:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return WorkerHealthResponse(
        status="ready" if active else "unavailable",
        active_workers=active,
        stale_workers=stale,
    )
