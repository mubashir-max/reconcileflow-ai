"""Password, token, and authenticated-user dependencies."""

from datetime import timedelta
from dataclasses import dataclass
import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from reconcileflow.auth import PasswordManager, TokenManager, TokenValidationError
from reconcileflow.persistence import DatabaseDependency, PersistenceUnitOfWork, UserRecord

from .errors import APIError


_password_manager = PasswordManager()


def get_password_manager() -> PasswordManager:
    return _password_manager


PasswordManagerDependency = Annotated[PasswordManager, Depends(get_password_manager)]


def get_token_manager(request: Request) -> TokenManager:
    settings = request.app.state.settings
    return TokenManager(
        secret=settings.token_signing_secret.get_secret_value(),
        issuer=settings.token_issuer,
        audience=settings.token_audience,
        access_ttl=timedelta(minutes=settings.access_token_ttl_minutes),
        refresh_ttl=timedelta(days=settings.refresh_token_ttl_days),
    )


TokenManagerDependency = Annotated[TokenManager, Depends(get_token_manager)]
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def get_current_user(
    credentials: BearerCredentials,
    tokens: TokenManagerDependency,
    database: DatabaseDependency,
) -> UserRecord:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(status_code=401, code="INVALID_ACCESS_TOKEN", message="A valid access token is required.")
    try:
        claims = tokens.decode_access(credentials.credentials)
    except TokenValidationError as error:
        raise APIError(status_code=401, code="INVALID_ACCESS_TOKEN", message="A valid access token is required.") from error
    with database.session() as session:
        user = PersistenceUnitOfWork(session).users.get(claims.subject)
        if user is None or not user.is_active:
            raise APIError(status_code=401, code="INVALID_ACCESS_TOKEN", message="A valid access token is required.")
        session.expunge(user)
        return user


CurrentUserDependency = Annotated[UserRecord, Depends(get_current_user)]


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str


def get_tenant_context(
    user: CurrentUserDependency,
    database: DatabaseDependency,
    organization_header: Annotated[str | None, Header(alias="X-Organization-ID")] = None,
) -> TenantContext:
    if organization_header is None:
        raise APIError(status_code=400, code="ORGANIZATION_REQUIRED", message="X-Organization-ID is required.")
    try:
        organization_id = uuid.UUID(organization_header)
    except (ValueError, TypeError) as error:
        raise APIError(status_code=400, code="INVALID_ORGANIZATION", message="X-Organization-ID must be a valid UUID.") from error
    with database.session() as session:
        membership = PersistenceUnitOfWork(session).memberships.get_active(
            organization_id=organization_id, user_id=user.id
        )
        if membership is None:
            raise APIError(status_code=403, code="ORGANIZATION_ACCESS_DENIED", message="Access to this organization is denied.")
        return TenantContext(organization_id=organization_id, user_id=user.id, role=membership.role)


TenantContextDependency = Annotated[TenantContext, Depends(get_tenant_context)]

RECONCILIATION_OPERATOR_ROLES = frozenset({"OWNER", "ADMIN", "ANALYST"})


def get_reconciliation_operator(tenant: TenantContextDependency) -> TenantContext:
    """Require a membership role allowed to change reconciliation data."""
    if tenant.role not in RECONCILIATION_OPERATOR_ROLES:
        raise APIError(
            status_code=403,
            code="INSUFFICIENT_ROLE",
            message="Your organization role does not permit this operation.",
        )
    return tenant


ReconciliationOperatorDependency = Annotated[TenantContext, Depends(get_reconciliation_operator)]

MEMBERSHIP_MANAGER_ROLES = frozenset({"OWNER", "ADMIN"})


def get_membership_manager(tenant: TenantContextDependency) -> TenantContext:
    """Require an organization role allowed to manage memberships."""
    if tenant.role not in MEMBERSHIP_MANAGER_ROLES:
        raise APIError(
            status_code=403,
            code="INSUFFICIENT_ROLE",
            message="Your organization role does not permit membership management.",
        )
    return tenant


MembershipManagerDependency = Annotated[TenantContext, Depends(get_membership_manager)]
