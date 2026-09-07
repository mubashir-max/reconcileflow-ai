"""Tenant-scoped security audit endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from reconcileflow.persistence import Page, PersistenceUnitOfWork, SessionDependency

from ..auth_dependencies import MembershipManagerDependency
from ..errors import APIError
from ..schemas import ErrorResponse
from ..security_audit_schemas import SecurityAuditEventListResponse, SecurityAuditEventResponse


router = APIRouter(prefix="/organizations/{organization_id}/security-audit-events", tags=["security audit"])


@router.get(
    "",
    response_model=SecurityAuditEventListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="List organization security audit events",
    description="Requires the OWNER or ADMIN role and returns events only for the selected organization.",
)
def list_security_audit_events(
    organization_id: uuid.UUID,
    session: SessionDependency,
    manager: MembershipManagerDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SecurityAuditEventListResponse:
    if organization_id != manager.organization_id:
        raise APIError(status_code=403, code="ORGANIZATION_ACCESS_DENIED", message="Access to this organization is denied.")
    repository = PersistenceUnitOfWork(session).security_audit_events
    records = repository.list_for_organization(organization_id, page=Page(limit, offset))
    return SecurityAuditEventListResponse(
        items=[SecurityAuditEventResponse.model_validate(item, from_attributes=True) for item in records],
        total=repository.count_for_organization(organization_id),
        limit=limit,
        offset=offset,
    )
