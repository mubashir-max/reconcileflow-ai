"""Organization discovery and profile management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency

from ..auth_dependencies import CurrentUserDependency, MembershipManagerDependency, TenantContextDependency
from ..errors import APIError
from ..organization_schemas import (
    OrganizationListItem,
    OrganizationListResponse,
    OrganizationProfileResponse,
    UpdateOrganizationRequest,
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
        work.organizations.update_name(record, request.name)
    return _profile(record, manager.role)
