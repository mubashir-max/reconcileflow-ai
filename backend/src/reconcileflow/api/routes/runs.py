"""Versioned endpoints for persistent reconciliation-run management."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency
from reconcileflow.reconciliation import ReconciliationConfig

from ..run_schemas import (
    CreateReconciliationRunRequest,
    ReconciliationConfigurationResponse,
    ReconciliationRunListItem,
    ReconciliationRunListResponse,
    ReconciliationRunResponse,
    ReconciliationRunStatus,
)
from ..schemas import ErrorResponse


router = APIRouter(prefix="/reconciliation-runs", tags=["reconciliation runs"])
ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "The reconciliation run does not exist."},
    409: {"model": ErrorResponse, "description": "The request conflicts with persisted data."},
    422: {"model": ErrorResponse, "description": "The request is invalid."},
}


def _configuration_response(record) -> ReconciliationConfigurationResponse:
    return ReconciliationConfigurationResponse(
        amount_tolerance=record.amount_tolerance.quantize(Decimal("0.0001")),
        date_tolerance_days=record.date_tolerance_days,
        maximum_group_size=int(record.settings["maximum_group_size"]),
    )


def _run_response(run, configuration) -> ReconciliationRunResponse:
    return ReconciliationRunResponse(
        id=run.id,
        status=run.status,
        configuration=_configuration_response(configuration),
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.post(
    "",
    response_model=ReconciliationRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reconciliation run",
    responses={409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422]},
)
def create_reconciliation_run(request: CreateReconciliationRunRequest, session: SessionDependency) -> ReconciliationRunResponse:
    domain_config = ReconciliationConfig(
        amount_tolerance=request.configuration.amount_tolerance,
        date_tolerance_days=request.configuration.date_tolerance_days,
        maximum_group_size=request.configuration.maximum_group_size,
    )
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
        configuration = work.configurations.add(run.id, domain_config)
    return _run_response(run, configuration)


@router.get(
    "/{run_id}",
    response_model=ReconciliationRunResponse,
    summary="Get a reconciliation run",
    responses={404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422]},
)
def get_reconciliation_run(run_id: uuid.UUID, session: SessionDependency) -> ReconciliationRunResponse:
    work = PersistenceUnitOfWork(session)
    run = work.runs.get(run_id)
    configuration = work.configurations.get_for_run(run_id)
    return _run_response(run, configuration)


@router.get(
    "",
    response_model=ReconciliationRunListResponse,
    summary="List reconciliation runs",
    responses={422: ERROR_RESPONSES[422]},
)
def list_reconciliation_runs(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    run_status: Annotated[ReconciliationRunStatus | None, Query(alias="status")] = None,
) -> ReconciliationRunListResponse:
    work = PersistenceUnitOfWork(session)
    status_value = run_status.value if run_status is not None else None
    records = work.runs.list(page=Page(limit=limit, offset=offset), status=status_value)
    return ReconciliationRunListResponse(
        items=[
            ReconciliationRunListItem(
                id=record.id,
                status=record.status,
                started_at=record.started_at,
                finished_at=record.finished_at,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ],
        total=work.runs.count(status=status_value),
        limit=limit,
        offset=offset,
    )
