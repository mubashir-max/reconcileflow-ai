"""Execute persisted runs and expose their explainable output."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Query

from reconcileflow.audit import AuditTrail
from reconcileflow.audit import AuditEventType
from reconcileflow.ingestion import load_bank_transactions, load_erp_invoices, load_gateway_settlements
from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationEngine

from ..errors import APIError
from ..execution_schemas import AuditEventListResponse, AuditEventResponse, ExecutionResponse, ReconciliationResultStatus, ResultListResponse, ResultResponse
from ..schemas import ErrorResponse
from ..storage_dependencies import FileStorageDependency


router = APIRouter(tags=["reconciliation execution"])
ERROR_RESPONSES = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


def _result(record) -> ResultResponse:
    return ResultResponse.model_validate(record, from_attributes=True)


def _audit(record) -> AuditEventResponse:
    return AuditEventResponse.model_validate(record, from_attributes=True)


@router.post("/reconciliation-runs/{run_id}/execute", response_model=ExecutionResponse, responses=ERROR_RESPONSES, summary="Execute a pending reconciliation run")
def execute_run(run_id: uuid.UUID, session: SessionDependency, storage: FileStorageDependency) -> ExecutionResponse:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.get(run_id, lock=True)
        if run.status != "PENDING":
            raise APIError(status_code=409, code="RUN_NOT_PENDING", message="Only a pending reconciliation run can be executed.")
        files = {item.source_type: item for item in work.source_files.list_for_run(run_id)}
        missing = sorted({"BANK_TRANSACTIONS", "ERP_INVOICES"} - files.keys())
        if missing:
            raise APIError(status_code=422, code="MISSING_SOURCE_FILES", message="Bank transactions and ERP invoices are required before execution.")
        config_record = work.configurations.get_for_run(run_id)
        work.runs.transition(run_id, "RUNNING")

    config = ReconciliationConfig(
        amount_tolerance=config_record.amount_tolerance,
        date_tolerance_days=config_record.date_tolerance_days,
        maximum_group_size=int(config_record.settings["maximum_group_size"]),
    )
    try:
        paths = {kind: storage.resolve(record.storage_key or "") for kind, record in files.items()}
        trail = AuditTrail()
        trail.run_id = str(run_id)
        trail.start(bank_path=paths["BANK_TRANSACTIONS"], erp_path=paths["ERP_INVOICES"], gateway_path=paths.get("GATEWAY_SETTLEMENTS"), output_path="database", output_format="DATABASE", config=config)
        trail.begin_stage("bank_ingestion")
        banks = load_bank_transactions(paths["BANK_TRANSACTIONS"])
        trail.ingestion_completed("bank", len(banks))
        trail.begin_stage("erp_ingestion")
        invoices = load_erp_invoices(paths["ERP_INVOICES"])
        trail.ingestion_completed("erp", len(invoices))
        trail.begin_stage("gateway_ingestion")
        if "GATEWAY_SETTLEMENTS" in paths:
            gateways = load_gateway_settlements(paths["GATEWAY_SETTLEMENTS"])
            trail.ingestion_completed("gateway", len(gateways))
        else:
            gateways = []
            trail.gateway_skipped()
        trail.begin_stage("reconciliation")
        results = ReconciliationEngine(config).reconcile(banks, invoices, gateways)
        counts = Counter(item.status.value for item in results)
        review_count = sum(item.requires_review for item in results)
        trail.reconciliation_completed(total=len(results), status_counts=dict(counts), review_count=review_count)
        trail.succeed()
        with PersistenceUnitOfWork(session) as work:
            work.results.add_many(run_id, results)
            for event in trail.events:
                work.audit_events.append(event)
            work.runs.transition(run_id, "SUCCEEDED")
        return ExecutionResponse(run_id=run_id, status="SUCCEEDED", result_count=len(results), results_requiring_review=review_count)
    except APIError:
        raise
    except Exception as error:
        if 'trail' in locals():
            trail.fail(error)
        with PersistenceUnitOfWork(session) as work:
            current = work.runs.get(run_id)
            if current.status == "RUNNING":
                if 'trail' in locals():
                    for event in trail.events:
                        if event.event is not AuditEventType.RUN_SUCCEEDED:
                            work.audit_events.append(event)
                work.runs.transition(run_id, "FAILED", error_code="EXECUTION_FAILED", error_message="Reconciliation execution failed.")
        raise APIError(status_code=422, code="EXECUTION_FAILED", message="Reconciliation execution failed. Check the source files and configuration.") from error


@router.get("/reconciliation-runs/{run_id}/results", response_model=ResultListResponse, responses=ERROR_RESPONSES, summary="List reconciliation results")
def list_results(run_id: uuid.UUID, session: SessionDependency, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0, result_status: Annotated[ReconciliationResultStatus | None, Query(alias="status")] = None, requires_review: bool | None = None) -> ResultListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id)
    status_value = result_status.value if result_status else None
    records = work.results.list_for_run(run_id, page=Page(limit, offset), status=status_value, requires_review=requires_review)
    return ResultListResponse(items=[_result(item) for item in records], total=work.results.count_for_run(run_id, status=status_value, requires_review=requires_review), limit=limit, offset=offset)


@router.get("/results/{result_id}", response_model=ResultResponse, responses=ERROR_RESPONSES, summary="Get a reconciliation result")
def get_result(result_id: uuid.UUID, session: SessionDependency) -> ResultResponse:
    return _result(PersistenceUnitOfWork(session).results.get(result_id))


@router.get("/reconciliation-runs/{run_id}/audit-events", response_model=AuditEventListResponse, responses=ERROR_RESPONSES, summary="List reconciliation audit events")
def list_audit_events(run_id: uuid.UUID, session: SessionDependency, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> AuditEventListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id)
    records = work.audit_events.list_for_run(run_id, page=Page(limit, offset))
    return AuditEventListResponse(items=[_audit(item) for item in records], total=work.audit_events.count_for_run(run_id), limit=limit, offset=offset)
