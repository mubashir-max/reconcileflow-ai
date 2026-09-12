"""Tenant-scoped generation and review of advisory AI match suggestions."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from reconcileflow.ai import AIInferenceError, CandidateSourceRecord, CandidateSourceType
from reconcileflow.ingestion import load_bank_transactions, load_erp_invoices, load_gateway_settlements
from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency
from reconcileflow.persistence.models import ReconciliationResultRecord
from reconcileflow.storage import StorageOperationError

from ..ai_suggestion_schemas import (
    AISuggestionDecisionRequest,
    AISuggestionGenerationResponse,
    AISuggestionListResponse,
    AISuggestionResponse,
    AISuggestionStatus,
)
from ..auth_dependencies import ReconciliationOperatorDependency, TenantContextDependency
from ..errors import APIError
from ..schemas import ErrorResponse


router = APIRouter(prefix="/ai-match-suggestions", tags=["AI match suggestions"])
ERROR_RESPONSES = {
    401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
    404: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
    422: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
}


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _response(record) -> AISuggestionResponse:
    explanation = record.explanation
    return AISuggestionResponse(
        id=record.id, run_id=record.run_id, status=record.status,
        bank_record_ids=record.bank_record_ids,
        erp_invoice_ids=record.erp_invoice_ids,
        gateway_record_ids=record.gateway_record_ids,
        confidence_score=float(record.confidence_score),
        summary=explanation["summary"], reason_codes=explanation["reason_codes"],
        model_version=record.model_version,
        prompt_version=record.prompt_template_version,
        reviewed_by_user_id=record.reviewed_by_user_id,
        reviewed_at=_utc(record.reviewed_at), expires_at=_utc(record.expires_at),
        created_at=_utc(record.created_at),
    )


@router.post(
    "/runs/{run_id}/generate", response_model=AISuggestionGenerationResponse,
    status_code=201, responses=ERROR_RESPONSES,
    summary="Generate advisory AI match suggestions",
    description="Requires OWNER, ADMIN, or ANALYST. Source records remain server-side.",
)
async def generate_suggestions(
    run_id: uuid.UUID, request: Request, tenant: ReconciliationOperatorDependency,
) -> AISuggestionGenerationResponse:
    database = request.app.state.database
    storage = request.app.state.file_storage
    with database.session() as session:
        work = PersistenceUnitOfWork(session)
        run = work.runs.get(run_id, organization_id=tenant.organization_id)
        if run.status != "SUCCEEDED":
            raise APIError(status_code=409, code="RUN_NOT_COMPLETED", message="Suggestions require a completed reconciliation run.")
        files = {item.source_type: item for item in work.source_files.list_for_run(run_id)}
        excluded: set[str] = set()
        resolved = session.scalars(select(ReconciliationResultRecord).where(
            ReconciliationResultRecord.run_id == run_id,
            ReconciliationResultRecord.requires_review.is_(False),
        ))
        for result in resolved:
            excluded.update(result.bank_source_record_ids)
            excluded.update(result.erp_invoice_ids)
            excluded.update(result.gateway_source_record_ids)
    if not {"BANK_TRANSACTIONS", "ERP_INVOICES"} <= files.keys():
        raise APIError(status_code=422, code="MISSING_SOURCE_FILES", message="Bank transactions and ERP invoices are required.")

    materializations = ExitStack()
    try:
        paths = {
            source_type: materializations.enter_context(storage.materialize(record.storage_key or ""))
            for source_type, record in files.items()
        }
        records = _candidate_records(
            tenant.organization_id, run_id,
            load_bank_transactions(paths["BANK_TRANSACTIONS"]),
            load_erp_invoices(paths["ERP_INVOICES"]),
            load_gateway_settlements(paths["GATEWAY_SETTLEMENTS"])
            if "GATEWAY_SETTLEMENTS" in paths else [],
        )
        with database.session() as session:
            created = await request.app.state.ai_match_suggestion_workflow.generate_and_persist(
                session=session, organization_id=tenant.organization_id, run_id=run_id,
                records=records, excluded_record_ids=frozenset(excluded),
            )
            if created:
                with PersistenceUnitOfWork(session) as work:
                    work.security_audit_events.append(
                        organization_id=tenant.organization_id, actor_user_id=tenant.user_id,
                        event_type="AI_SUGGESTIONS_GENERATED",
                        details={"run_id": str(run_id), "suggestion_count": len(created)},
                    )
            return AISuggestionGenerationResponse(
                items=[_response(item) for item in created], generated_count=len(created)
            )
    except APIError:
        raise
    except AIInferenceError as error:
        raise APIError(status_code=503, code="AI_INFERENCE_UNAVAILABLE", message="AI-assisted matching is temporarily unavailable.") from error
    except StorageOperationError as error:
        raise APIError(status_code=503, code="STORAGE_UNAVAILABLE", message="Object storage is temporarily unavailable.") from error
    finally:
        materializations.close()


@router.get("/runs/{run_id}", response_model=AISuggestionListResponse, responses=ERROR_RESPONSES)
def list_suggestions(
    run_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    suggestion_status: Annotated[AISuggestionStatus | None, Query(alias="status")] = None,
) -> AISuggestionListResponse:
    work = PersistenceUnitOfWork(session)
    work.runs.get(run_id, organization_id=tenant.organization_id)
    records = work.ai_match_suggestions.list_for_run(
        run_id, organization_id=tenant.organization_id, page=Page(limit, offset),
        status=suggestion_status.value if suggestion_status else None,
    )
    total = work.ai_match_suggestions.count_for_run(
        run_id, organization_id=tenant.organization_id,
        status=suggestion_status.value if suggestion_status else None,
    )
    return AISuggestionListResponse(
        items=[_response(item) for item in records], total=total, limit=limit, offset=offset
    )


@router.get("/{suggestion_id}", response_model=AISuggestionResponse, responses=ERROR_RESPONSES)
def get_suggestion(
    suggestion_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency,
) -> AISuggestionResponse:
    return _response(PersistenceUnitOfWork(session).ai_match_suggestions.get(
        suggestion_id, organization_id=tenant.organization_id
    ))


@router.post("/{suggestion_id}/decision", response_model=AISuggestionResponse, responses=ERROR_RESPONSES)
def decide_suggestion(
    suggestion_id: uuid.UUID, request: AISuggestionDecisionRequest,
    session: SessionDependency, tenant: ReconciliationOperatorDependency,
) -> AISuggestionResponse:
    with PersistenceUnitOfWork(session) as work:
        record = work.ai_match_suggestions.resolve(
            suggestion_id, organization_id=tenant.organization_id,
            reviewer_user_id=tenant.user_id, decision=request.decision.value,
            reviewed_at=datetime.now(UTC),
        )
        work.security_audit_events.append(
            organization_id=tenant.organization_id, actor_user_id=tenant.user_id,
            event_type=f"AI_SUGGESTION_{request.decision.value}",
            details={"suggestion_id": str(suggestion_id), "run_id": str(record.run_id)},
        )
    return _response(record)


def _candidate_records(organization_id, run_id, banks, invoices, gateways):
    records: list[CandidateSourceRecord] = []
    for item in banks:
        records.append(CandidateSourceRecord(
            organization_id=organization_id, run_id=run_id,
            source_type=CandidateSourceType.BANK, record_id=item.source_record_id,
            amount=item.amount, effective_date=item.booking_date, currency=item.currency,
            references=tuple(filter(None, (
                item.transaction_id, item.entry_reference, item.end_to_end_id,
                item.invoice_reference, item.customer_reference, item.bank_reference,
            ))),
        ))
    for item in invoices:
        records.append(CandidateSourceRecord(
            organization_id=organization_id, run_id=run_id,
            source_type=CandidateSourceType.ERP, record_id=item.invoice_id,
            amount=item.amount_due, effective_date=item.issue_date, currency=item.currency,
            references=tuple(filter(None, (
                item.invoice_id, item.invoice_number, item.payment_reference,
                item.purchase_order_reference, item.sales_order_reference,
            ))),
        ))
    for item in gateways:
        records.append(CandidateSourceRecord(
            organization_id=organization_id, run_id=run_id,
            source_type=CandidateSourceType.GATEWAY, record_id=item.source_record_id,
            amount=item.net_amount, effective_date=item.settlement_date,
            currency=item.settlement_currency,
            references=tuple(filter(None, (
                item.settlement_id, item.gateway_payment_id, item.invoice_reference,
                item.order_reference, item.gateway_reference, item.bank_reference,
            ))),
        ))
    return tuple(records)
