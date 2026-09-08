"""Tenant-scoped background-job monitoring and cancellation endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency
from reconcileflow.persistence.errors import InvalidStatusTransitionError

from ..auth_dependencies import ReconciliationOperatorDependency, TenantContextDependency
from ..errors import APIError
from ..job_schemas import BackgroundJobListResponse, BackgroundJobResponse, BackgroundJobStatusValue
from ..schemas import ErrorResponse


router = APIRouter(prefix="/background-jobs", tags=["background jobs"])
ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _response(record) -> BackgroundJobResponse:
    return BackgroundJobResponse(
        id=record.id,
        run_id=record.run_id,
        organization_id=record.organization_id,
        status=record.status,
        progress_percentage=record.progress_percentage,
        status_message=record.status_message,
        attempt_count=record.attempt_count,
        max_attempts=record.max_attempts,
        failure_code=record.failure_code,
        failure_message=record.failure_message,
        scheduled_at=record.scheduled_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        cancellation_requested_at=record.cancellation_requested_at,
        retry_at=record.retry_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=BackgroundJobListResponse, responses=ERROR_RESPONSES)
def list_background_jobs(
    session: SessionDependency,
    tenant: TenantContextDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    job_status: Annotated[BackgroundJobStatusValue | None, Query(alias="status")] = None,
) -> BackgroundJobListResponse:
    work = PersistenceUnitOfWork(session)
    records = work.background_jobs.list(
        organization_id=tenant.organization_id,
        status=job_status.value if job_status else None,
        page=Page(limit=limit, offset=offset),
    )
    return BackgroundJobListResponse(
        items=[_response(record) for record in records],
        total=work.background_jobs.count(
            organization_id=tenant.organization_id,
            status=job_status.value if job_status else None,
        ),
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=BackgroundJobResponse, responses=ERROR_RESPONSES)
def get_background_job(
    job_id: uuid.UUID,
    session: SessionDependency,
    tenant: TenantContextDependency,
) -> BackgroundJobResponse:
    return _response(
        PersistenceUnitOfWork(session).background_jobs.get(
            job_id, organization_id=tenant.organization_id
        )
    )


@router.post(
    "/{job_id}/cancel",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_200_OK,
    description="Requires the OWNER, ADMIN, or ANALYST organization role.",
    responses=ERROR_RESPONSES,
)
def cancel_background_job(
    job_id: uuid.UUID,
    session: SessionDependency,
    tenant: ReconciliationOperatorDependency,
) -> BackgroundJobResponse:
    try:
        with PersistenceUnitOfWork(session) as work:
            record = work.background_jobs.request_cancellation(
                job_id, organization_id=tenant.organization_id
            )
    except InvalidStatusTransitionError as error:
        raise APIError(
            status_code=409,
            code="JOB_NOT_CANCELLABLE",
            message="The background job cannot be cancelled in its current state.",
        ) from error
    return _response(record)
