"""Password, token, and authenticated-user dependencies."""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from reconcileflow.auth import PasswordManager, TokenManager, TokenValidationError
from reconcileflow.persistence import PersistenceUnitOfWork, SessionDependency, UserRecord

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
    session: SessionDependency,
) -> UserRecord:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(status_code=401, code="INVALID_ACCESS_TOKEN", message="A valid access token is required.")
    try:
        claims = tokens.decode_access(credentials.credentials)
    except TokenValidationError as error:
        raise APIError(status_code=401, code="INVALID_ACCESS_TOKEN", message="A valid access token is required.") from error
    user = PersistenceUnitOfWork(session).users.get(claims.subject)
    if user is None or not user.is_active:
        raise APIError(status_code=401, code="INVALID_ACCESS_TOKEN", message="A valid access token is required.")
    return user


CurrentUserDependency = Annotated[UserRecord, Depends(get_current_user)]
