"""Organization membership management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from reconcileflow.persistence import PersistenceConflictError, PersistenceUnitOfWork, SessionDependency

from ..auth_dependencies import MembershipManagerDependency
from ..errors import APIError
from ..membership_schemas import (
    AddOrganizationMemberRequest,
    MemberUserResponse,
    OrganizationMemberListResponse,
    OrganizationMemberResponse,
    UpdateOrganizationMemberRequest,
)
from ..schemas import ErrorResponse


router = APIRouter(prefix="/organizations/{organization_id}/members", tags=["organization members"])
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _ensure_selected(organization_id: uuid.UUID, manager: MembershipManagerDependency) -> None:
    if organization_id != manager.organization_id:
        raise APIError(status_code=403, code="ORGANIZATION_ACCESS_DENIED", message="Access to this organization is denied.")


def _response(record) -> OrganizationMemberResponse:
    return OrganizationMemberResponse(
        id=record.id,
        organization_id=record.organization_id,
        user=MemberUserResponse(
            id=record.user.id,
            email=record.user.email,
            display_name=record.user.display_name,
            is_active=record.user.is_active,
        ),
        role=record.role,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _ensure_admin_can_manage(manager: MembershipManagerDependency, target_role: str, requested_role: str | None = None) -> None:
    if manager.role == "ADMIN" and (target_role == "OWNER" or requested_role == "OWNER"):
        raise APIError(status_code=403, code="OWNER_ROLE_REQUIRED", message="Only an organization owner can manage owner memberships.")


@router.get(
    "",
    response_model=OrganizationMemberListResponse,
    responses=ERROR_RESPONSES,
    summary="List organization members",
    description="Requires the OWNER or ADMIN organization role.",
)
def list_members(organization_id: uuid.UUID, session: SessionDependency, manager: MembershipManagerDependency) -> OrganizationMemberListResponse:
    _ensure_selected(organization_id, manager)
    records = PersistenceUnitOfWork(session).memberships.list_for_organization(organization_id)
    return OrganizationMemberListResponse(items=[_response(item) for item in records], total=len(records))


@router.post(
    "",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    summary="Add an organization member",
    description="Requires OWNER or ADMIN. Only OWNER can assign the OWNER role.",
)
def add_member(organization_id: uuid.UUID, request: AddOrganizationMemberRequest, session: SessionDependency, manager: MembershipManagerDependency) -> OrganizationMemberResponse:
    _ensure_selected(organization_id, manager)
    _ensure_admin_can_manage(manager, request.role.value, request.role.value)
    with PersistenceUnitOfWork(session) as work:
        user = work.users.get_by_email(request.email)
        if user is None or not user.is_active:
            raise APIError(status_code=404, code="USER_NOT_FOUND", message="The requested user was not found.")
        if work.memberships.get_for_user(organization_id=organization_id, user_id=user.id) is not None:
            raise PersistenceConflictError("the user already has an organization membership")
        membership = work.memberships.create(
            organization_id=organization_id, user_id=user.id, role=request.role.value
        )
        membership.user = user
    return _response(membership)


@router.patch(
    "/{membership_id}",
    response_model=OrganizationMemberResponse,
    responses=ERROR_RESPONSES,
    summary="Update an organization member role",
    description="Requires OWNER or ADMIN. Only OWNER can manage the OWNER role.",
)
def update_member(organization_id: uuid.UUID, membership_id: uuid.UUID, request: UpdateOrganizationMemberRequest, session: SessionDependency, manager: MembershipManagerDependency) -> OrganizationMemberResponse:
    _ensure_selected(organization_id, manager)
    with PersistenceUnitOfWork(session) as work:
        membership = work.memberships.get(membership_id, organization_id=organization_id, lock=True)
        _ensure_admin_can_manage(manager, membership.role, request.role.value)
        if membership.role == "OWNER" and request.role.value != "OWNER" and work.memberships.count_active_owners(organization_id) <= 1:
            raise APIError(status_code=409, code="FINAL_OWNER_REQUIRED", message="The final active owner cannot be demoted.")
        work.memberships.set_role(membership, request.role.value)
    return _response(membership)


@router.delete(
    "/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROR_RESPONSES,
    summary="Deactivate an organization membership",
    description="Requires OWNER or ADMIN. Only OWNER can manage the OWNER role.",
)
def deactivate_member(organization_id: uuid.UUID, membership_id: uuid.UUID, session: SessionDependency, manager: MembershipManagerDependency) -> Response:
    _ensure_selected(organization_id, manager)
    with PersistenceUnitOfWork(session) as work:
        membership = work.memberships.get(membership_id, organization_id=organization_id, lock=True)
        _ensure_admin_can_manage(manager, membership.role)
        if not membership.is_active:
            raise APIError(status_code=409, code="MEMBERSHIP_INACTIVE", message="The membership is already inactive.")
        if membership.role == "OWNER" and work.memberships.count_active_owners(organization_id) <= 1:
            raise APIError(status_code=409, code="FINAL_OWNER_REQUIRED", message="The final active owner cannot be removed.")
        work.memberships.deactivate(membership)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
