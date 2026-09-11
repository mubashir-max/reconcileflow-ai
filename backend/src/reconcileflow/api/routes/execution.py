"""Execute persisted runs and expose their explainable output."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency

from ..errors import APIError
from ..auth_dependencies import ReconciliationOperatorDependency, TenantContextDependency, get_tenant_context
from ..execution_schemas import AuditEventListResponse, AuditEventResponse, ExecutionAcceptedResponse, ExecutionRequest, ReconciliationResultStatus, ResultListResponse, ResultResponse
from ..schemas import ErrorResponse


router = APIRouter(
    tags=["reconciliation execution"],
    dependencies=[Depends(get_tenant_context)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
ERROR_RESPONSES = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


def _result(record) -> ResultResponse:
    return ResultResponse.model_validate(record, from_attributes=True)


def _audit(record) -> AuditEventResponse:
    return AuditEventResponse.model_validate(record, from_attributes=True)


@router.post(
    "/reconciliation-runs/{run_id}/execute",
    response_model=ExecutionAcceptedResponse,
    status_code=202,
    responses=ERROR_RESPONSES,
    summary="Execute a pending reconciliation run",
    description="Requires the OWNER, ADMIN, or ANALYST organization role.",
)
def execute_run(
    run_id: uuid.UUID,
    api_request: Request,
    session: SessionDependency,
    tenant: ReconciliationOperatorDependency,
    request: ExecutionRequest | None = None,
) -> ExecutionAcceptedResponse:
    now = datetime.now(UTC)
    scheduled_at = request.scheduled_at.astimezone(UTC) if request and request.scheduled_at else now
    if scheduled_at < now:
        raise APIError(
            status_code=422,
            code="SCHEDULE_IN_PAST",
            message="The execution schedule must not be in the past.",
        )
    if scheduled_at > now + timedelta(days=365):
        raise APIError(
            status_code=422,
            code="SCHEDULE_TOO_DISTANT",
            message="The execution schedule must be within 365 days.",
        )
    timeout_seconds = (
        request.timeout_seconds
        if request and request.timeout_seconds is not None
        else api_request.app.state.settings.default_job_timeout_seconds
    )
    if timeout_seconds > api_request.app.state.settings.maximum_job_timeout_seconds:
        raise APIError(
            status_code=422,
            code="JOB_TIMEOUT_TOO_LARGE",
            message="The execution timeout exceeds the permitted maximum.",
        )
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.get(run_id, organization_id=tenant.organization_id, lock=True)
        if run.status != "PENDING":
            raise APIError(status_code=409, code="RUN_NOT_PENDING", message="Only a pending reconciliation run can be executed.")
        files = {item.source_type: item for item in work.source_files.list_for_run(run_id)}
        missing = sorted({"BANK_TRANSACTIONS", "ERP_INVOICES"} - files.keys())
        if missing:
            raise APIError(status_code=422, code="MISSING_SOURCE_FILES", message="Bank transactions and ERP invoices are required before execution.")
        work.configurations.get_for_run(run_id)
        if work.background_jobs.get_for_run(
            run_id, organization_id=tenant.organization_id
        ) is not None:
            raise APIError(
                status_code=409,
                code="EXECUTION_ALREADY_QUEUED",
                message="Execution has already been queued for this run.",
            )
        job = work.background_jobs.create(
            organization_id=tenant.organization_id,
            run_id=run_id,
            scheduled_at=scheduled_at,
            timeout_seconds=timeout_seconds,
        )
    return ExecutionAcceptedResponse(
        job_id=job.id,
        run_id=run_id,
        status="QUEUED",
        scheduled_at=job.scheduled_at,
        timeout_seconds=job.timeout_seconds,
    )


@router.get("/reconciliation-runs/{run_id}/results", response_model=ResultListResponse, responses=ERROR_RESPONSES, summary="List reconciliation results")
def list_results(run_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0, result_status: Annotated[ReconciliationResultStatus | None, Query(alias="status")] = None, requires_review: bool | None = None) -> ResultListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id, organization_id=tenant.organization_id)
    status_value = result_status.value if result_status else None
    records = work.results.list_for_run(run_id, page=Page(limit, offset), status=status_value, requires_review=requires_review)
    return ResultListResponse(items=[_result(item) for item in records], total=work.results.count_for_run(run_id, status=status_value, requires_review=requires_review), limit=limit, offset=offset)


@router.get("/results/{result_id}", response_model=ResultResponse, responses=ERROR_RESPONSES, summary="Get a reconciliation result")
def get_result(result_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency) -> ResultResponse:
    return _result(PersistenceUnitOfWork(session).results.get(result_id, organization_id=tenant.organization_id))


@router.get("/reconciliation-runs/{run_id}/audit-events", response_model=AuditEventListResponse, responses=ERROR_RESPONSES, summary="List reconciliation audit events")
def list_audit_events(run_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> AuditEventListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id, organization_id=tenant.organization_id)
    records = work.audit_events.list_for_run(run_id, page=Page(limit, offset))
    return AuditEventListResponse(items=[_audit(item) for item in records], total=work.audit_events.count_for_run(run_id), limit=limit, offset=offset)
