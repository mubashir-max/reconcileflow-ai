"""Registration and password credential verification endpoints."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, status

from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency

from ..auth_dependencies import PasswordManagerDependency
from ..auth_schemas import (
    LoginRequest,
    LoginResponse,
    MembershipResponse,
    OrganizationResponse,
    RegistrationRequest,
    RegistrationResponse,
    UserResponse,
)
from ..errors import APIError
from ..schemas import ErrorResponse


router = APIRouter(prefix="/auth", tags=["authentication"])
ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "The supplied credentials are invalid."},
    409: {"model": ErrorResponse, "description": "The email address is already registered."},
    422: {"model": ErrorResponse, "description": "The request is invalid."},
}


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return value[:80] or "organization"


def _user_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _membership_response(membership) -> MembershipResponse:
    organization = membership.organization
    return MembershipResponse(
        organization=OrganizationResponse(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            is_active=organization.is_active,
        ),
        role=membership.role,
        is_active=membership.is_active,
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a user and organization",
    responses={409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422]},
)
def register(
    request: RegistrationRequest,
    session: SessionDependency,
    passwords: PasswordManagerDependency,
) -> RegistrationResponse:
    password_hash = passwords.hash(request.password)
    base_slug = _slug(request.organization_name)
    work = PersistenceUnitOfWork(session)
    with work:
        if work.users.email_exists(request.email):
            raise APIError(status_code=409, code="EMAIL_ALREADY_REGISTERED", message="An account with this email already exists.")
        slug = base_slug
        while work.organizations.slug_exists(slug):
            slug = f"{base_slug[:70]}-{uuid.uuid4().hex[:8]}"
        user = work.users.create(
            email=request.email,
            password_hash=password_hash,
            display_name=request.display_name,
        )
        organization = work.organizations.create(name=request.organization_name, slug=slug)
        membership = work.memberships.create(
            organization_id=organization.id, user_id=user.id, role="OWNER"
        )
    return RegistrationResponse(
        user=_user_response(user), membership=_membership_response(membership)
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Verify email and password credentials",
    responses={401: ERROR_RESPONSES[401], 422: ERROR_RESPONSES[422]},
)
def login(
    request: LoginRequest,
    session: SessionDependency,
    passwords: PasswordManagerDependency,
) -> LoginResponse:
    work = PersistenceUnitOfWork(session)
    user = work.users.get_by_email(request.email)
    if user is None:
        passwords.verify_dummy(request.password)
        raise APIError(status_code=401, code="INVALID_CREDENTIALS", message="The email or password is incorrect.")
    if not passwords.verify(request.password, user.password_hash) or not user.is_active:
        raise APIError(status_code=401, code="INVALID_CREDENTIALS", message="The email or password is incorrect.")

    memberships = [
        membership
        for membership in work.memberships.list_for_user(user.id)
        if membership.is_active and membership.organization.is_active
    ]
    return LoginResponse(
        authenticated=True,
        user=_user_response(user),
        memberships=[_membership_response(item) for item in memberships],
    )
