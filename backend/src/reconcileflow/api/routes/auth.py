"""Registration and password credential verification endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status

from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency

from reconcileflow.auth import TokenValidationError

from ..auth_dependencies import CurrentUserDependency, PasswordManagerDependency, TokenManagerDependency
from ..auth_schemas import (
    LoginRequest,
    LoginResponse,
    CurrentUserResponse,
    MembershipResponse,
    OrganizationResponse,
    RegistrationRequest,
    RegistrationResponse,
    RefreshTokenRequest,
    TokenPairResponse,
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


def _now() -> datetime:
    return datetime.now(UTC)


def _database_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
    tokens: TokenManagerDependency,
) -> LoginResponse:
    work = PersistenceUnitOfWork(session)
    with work:
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
        access = tokens.issue_access(user.id)
        refresh = tokens.issue_refresh(user.id)
        work.refresh_tokens.create(
            token_id=refresh.token_id,
            user_id=user.id,
            family_id=uuid.uuid4(),
            token_hash=tokens.hash_refresh_token(refresh.value),
            expires_at=refresh.expires_at,
        )
    return LoginResponse(
        authenticated=True,
        user=_user_response(user),
        memberships=[_membership_response(item) for item in memberships],
        access_token=access.value,
        refresh_token=refresh.value,
        expires_in=int((access.expires_at - _now()).total_seconds()),
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Rotate a refresh token",
    responses={401: ERROR_RESPONSES[401], 422: ERROR_RESPONSES[422]},
)
def refresh_tokens(
    request: RefreshTokenRequest,
    session: SessionDependency,
    tokens: TokenManagerDependency,
) -> TokenPairResponse:
    try:
        claims = tokens.decode_refresh(request.refresh_token)
    except TokenValidationError as error:
        raise APIError(status_code=401, code="INVALID_REFRESH_TOKEN", message="The refresh token is invalid.") from error

    now = _now()
    replacement = tokens.issue_refresh(claims.subject)
    access = tokens.issue_access(claims.subject)
    invalid = False
    reused = False
    work = PersistenceUnitOfWork(session)
    with work:
        record = work.refresh_tokens.get_by_hash(tokens.hash_refresh_token(request.refresh_token), lock=True)
        if record is None or record.id != claims.token_id or record.user_id != claims.subject:
            invalid = True
        elif record.revoked_at is not None:
            work.refresh_tokens.revoke_family(record.family_id, at=now)
            reused = True
        elif _database_utc(record.expires_at) <= now:
            work.refresh_tokens.revoke(record, at=now)
            invalid = True
        else:
            user = work.users.get(record.user_id)
            if user is None or not user.is_active:
                work.refresh_tokens.revoke_family(record.family_id, at=now)
                invalid = True
            else:
                work.refresh_tokens.rotate(
                    record,
                    replacement_id=replacement.token_id,
                    replacement_hash=tokens.hash_refresh_token(replacement.value),
                    replacement_expires_at=replacement.expires_at,
                    at=now,
                )
    if reused:
        raise APIError(status_code=401, code="REFRESH_TOKEN_REUSED", message="The refresh token is invalid.")
    if invalid:
        raise APIError(status_code=401, code="INVALID_REFRESH_TOKEN", message="The refresh token is invalid.")
    return TokenPairResponse(
        access_token=access.value,
        refresh_token=replacement.value,
        expires_in=int((access.expires_at - now).total_seconds()),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
    responses={401: ERROR_RESPONSES[401], 422: ERROR_RESPONSES[422]},
)
def logout(
    request: RefreshTokenRequest,
    session: SessionDependency,
    tokens: TokenManagerDependency,
) -> None:
    try:
        claims = tokens.decode_refresh(request.refresh_token)
    except TokenValidationError as error:
        raise APIError(status_code=401, code="INVALID_REFRESH_TOKEN", message="The refresh token is invalid.") from error
    work = PersistenceUnitOfWork(session)
    invalid = False
    with work:
        record = work.refresh_tokens.get_by_hash(tokens.hash_refresh_token(request.refresh_token), lock=True)
        if record is None or record.id != claims.token_id or record.user_id != claims.subject:
            invalid = True
        else:
            work.refresh_tokens.revoke(record, at=_now())
    if invalid:
        raise APIError(status_code=401, code="INVALID_REFRESH_TOKEN", message="The refresh token is invalid.")


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Get the authenticated user",
    responses={401: ERROR_RESPONSES[401]},
)
def current_user(user: CurrentUserDependency, session: SessionDependency) -> CurrentUserResponse:
    work = PersistenceUnitOfWork(session)
    memberships = [
        item for item in work.memberships.list_for_user(user.id)
        if item.is_active and item.organization.is_active
    ]
    return CurrentUserResponse(
        user=_user_response(user),
        memberships=[_membership_response(item) for item in memberships],
    )
