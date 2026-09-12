"""Organization discovery and profile management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request

from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency, StorageQuotaExceededError

from ..auth_dependencies import CurrentUserDependency, MembershipManagerDependency, TenantContextDependency
from ..errors import APIError
from ..organization_schemas import (
    OrganizationListItem,
    OrganizationListResponse,
    OrganizationProfileResponse,
    UpdateOrganizationRequest,
    OrganizationStorageUsageResponse,
    UpdateOrganizationStorageQuotaRequest,
    OrganizationAIUsagePolicy,
    OrganizationAIUsageResponse,
    UpdateOrganizationAIUsagePolicyRequest,
    AIInferenceEventListResponse,
    AIInferenceEventResponse,
)
from ..schemas import ErrorResponse


router = APIRouter(prefix="/organizations", tags=["organizations"])
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _ensure_selected(organization_id: uuid.UUID, selected_organization_id: uuid.UUID) -> None:
    if organization_id != selected_organization_id:
        raise APIError(
            status_code=403,
            code="ORGANIZATION_ACCESS_DENIED",
            message="Access to this organization is denied.",
        )


def _profile(record, role: str) -> OrganizationProfileResponse:
    return OrganizationProfileResponse(
        id=record.id,
        name=record.name,
        slug=record.slug,
        is_active=record.is_active,
        current_user_role=role,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get(
    "",
    response_model=OrganizationListResponse,
    responses=ERROR_RESPONSES,
    summary="List available organizations",
    description="Lists active organizations where the authenticated user has an active membership. No organization header is required.",
)
def list_organizations(user: CurrentUserDependency, session: SessionDependency) -> OrganizationListResponse:
    memberships = PersistenceUnitOfWork(session).memberships.list_for_user(user.id)
    items = [
        OrganizationListItem(
            id=membership.organization.id,
            name=membership.organization.name,
            slug=membership.organization.slug,
            role=membership.role,
        )
        for membership in memberships
        if membership.is_active and membership.organization.is_active
    ]
    return OrganizationListResponse(items=items, total=len(items))


@router.get(
    "/{organization_id}",
    response_model=OrganizationProfileResponse,
    responses=ERROR_RESPONSES,
    summary="Get organization profile",
    description="Requires an active membership in the selected organization.",
)
def get_organization(
    organization_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency
) -> OrganizationProfileResponse:
    _ensure_selected(organization_id, tenant.organization_id)
    record = PersistenceUnitOfWork(session).organizations.get(organization_id)
    return _profile(record, tenant.role)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationProfileResponse,
    responses=ERROR_RESPONSES,
    summary="Update organization profile",
    description="Requires the OWNER or ADMIN organization role. Only the display name can be changed; the ID and slug remain stable.",
)
def update_organization(
    organization_id: uuid.UUID,
    request: UpdateOrganizationRequest,
    session: SessionDependency,
    manager: MembershipManagerDependency,
) -> OrganizationProfileResponse:
    _ensure_selected(organization_id, manager.organization_id)
    with PersistenceUnitOfWork(session) as work:
        record = work.organizations.get(organization_id)
        previous_name = record.name
        work.organizations.update_name(record, request.name)
        work.security_audit_events.append(
            organization_id=organization_id,
            actor_user_id=manager.user_id,
            event_type="ORGANIZATION_PROFILE_UPDATED",
            details={"previous_name": previous_name, "new_name": record.name},
        )
    return _profile(record, manager.role)


def _storage_usage(record) -> OrganizationStorageUsageResponse:
    remaining = None if record.storage_quota_bytes is None else max(record.storage_quota_bytes - record.storage_used_bytes, 0)
    utilization = None if record.storage_quota_bytes is None else (
        100.0 if record.storage_quota_bytes == 0 else min(100.0, record.storage_used_bytes * 100 / record.storage_quota_bytes)
    )
    return OrganizationStorageUsageResponse(
        organization_id=record.id, used_bytes=record.storage_used_bytes,
        quota_bytes=record.storage_quota_bytes, remaining_bytes=remaining,
        utilization_percent=utilization,
    )


@router.get("/{organization_id}/storage-usage", response_model=OrganizationStorageUsageResponse, responses=ERROR_RESPONSES)
def get_storage_usage(organization_id: uuid.UUID, session: SessionDependency, tenant: TenantContextDependency) -> OrganizationStorageUsageResponse:
    _ensure_selected(organization_id, tenant.organization_id)
    return _storage_usage(PersistenceUnitOfWork(session).organizations.get(organization_id))


@router.patch("/{organization_id}/storage-quota", response_model=OrganizationStorageUsageResponse, responses=ERROR_RESPONSES)
def update_storage_quota(
    organization_id: uuid.UUID, request: UpdateOrganizationStorageQuotaRequest,
    session: SessionDependency, manager: MembershipManagerDependency,
) -> OrganizationStorageUsageResponse:
    _ensure_selected(organization_id, manager.organization_id)
    try:
        with PersistenceUnitOfWork(session) as work:
            record = work.organizations.get(organization_id, lock=True)
            previous = record.storage_quota_bytes
            work.organizations.update_storage_quota(record, request.quota_bytes)
            work.security_audit_events.append(
                organization_id=organization_id, actor_user_id=manager.user_id,
                event_type="ORGANIZATION_STORAGE_QUOTA_UPDATED",
                details={"previous_quota_bytes": previous, "new_quota_bytes": record.storage_quota_bytes},
            )
    except StorageQuotaExceededError as error:
        raise APIError(status_code=409, code="STORAGE_QUOTA_BELOW_USAGE", message="The quota cannot be lower than current storage usage.") from error
    return _storage_usage(record)


def _ai_policy(record) -> OrganizationAIUsagePolicy:
    return OrganizationAIUsagePolicy(
        organization_id=record.id, hosted_ai_enabled=record.hosted_ai_enabled,
        daily_request_limit=record.ai_daily_request_limit,
        monthly_request_limit=record.ai_monthly_request_limit,
        daily_token_limit=record.ai_daily_token_limit,
        monthly_token_limit=record.ai_monthly_token_limit,
    )


@router.get("/{organization_id}/ai-usage", response_model=OrganizationAIUsageResponse, responses=ERROR_RESPONSES)
def get_ai_usage(
    organization_id: uuid.UUID, request: Request,
    session: SessionDependency, tenant: TenantContextDependency,
) -> OrganizationAIUsageResponse:
    _ensure_selected(organization_id, tenant.organization_id)
    record = PersistenceUnitOfWork(session).organizations.get(organization_id)
    summary = request.app.state.ai_usage_controller.summary(organization_id)
    return OrganizationAIUsageResponse(
        **_ai_policy(record).model_dump(),
        daily_requests=summary.daily_requests, daily_tokens=summary.daily_tokens,
        monthly_requests=summary.monthly_requests, monthly_tokens=summary.monthly_tokens,
    )


@router.patch("/{organization_id}/ai-usage-policy", response_model=OrganizationAIUsagePolicy, responses=ERROR_RESPONSES)
def update_ai_usage_policy(
    organization_id: uuid.UUID, request: UpdateOrganizationAIUsagePolicyRequest,
    session: SessionDependency, manager: MembershipManagerDependency,
) -> OrganizationAIUsagePolicy:
    _ensure_selected(organization_id, manager.organization_id)
    with PersistenceUnitOfWork(session) as work:
        record = work.organizations.get(organization_id, lock=True)
        work.organizations.update_ai_usage_policy(
            record, hosted_ai_enabled=request.hosted_ai_enabled,
            daily_request_limit=request.daily_request_limit,
            monthly_request_limit=request.monthly_request_limit,
            daily_token_limit=request.daily_token_limit,
            monthly_token_limit=request.monthly_token_limit,
        )
        work.security_audit_events.append(
            organization_id=organization_id, actor_user_id=manager.user_id,
            event_type="ORGANIZATION_AI_USAGE_POLICY_UPDATED",
            details={
                "hosted_ai_enabled": record.hosted_ai_enabled,
                "daily_request_limit": record.ai_daily_request_limit,
                "monthly_request_limit": record.ai_monthly_request_limit,
                "daily_token_limit": record.ai_daily_token_limit,
                "monthly_token_limit": record.ai_monthly_token_limit,
            },
        )
    return _ai_policy(record)


@router.get("/{organization_id}/ai-inference-events", response_model=AIInferenceEventListResponse, responses=ERROR_RESPONSES)
def list_ai_inference_events(
    organization_id: uuid.UUID, session: SessionDependency,
    tenant: TenantContextDependency, outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> AIInferenceEventListResponse:
    _ensure_selected(organization_id, tenant.organization_id)
    records = PersistenceUnitOfWork(session).ai_inference_events.list_for_organization(
        organization_id, page=Page(limit=limit, offset=offset), outcome=outcome,
    )
    return AIInferenceEventListResponse(items=[AIInferenceEventResponse.model_validate({
        "id": item.id, "run_id": item.run_id, "outcome": item.outcome,
        "provider": item.provider, "model_version": item.model_version,
        "prompt_version": item.prompt_version,
        "inference_config_version": item.inference_config_version,
        "candidate_count": item.candidate_count, "suggestion_count": item.suggestion_count,
        "input_tokens": item.input_tokens, "output_tokens": item.output_tokens,
        "duration_ms": item.duration_ms, "error_code": item.error_code,
        "created_at": item.created_at, "completed_at": item.completed_at,
    }) for item in records])
