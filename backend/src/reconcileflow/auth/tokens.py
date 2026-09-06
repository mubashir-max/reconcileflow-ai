"""Signed access/refresh token creation and strict validation."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal

import jwt
from jwt.exceptions import InvalidTokenError


class TokenValidationError(ValueError):
    """Raised when a token cannot be trusted."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: uuid.UUID
    token_id: uuid.UUID
    token_type: Literal["access", "refresh"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedToken:
    value: str
    token_id: uuid.UUID
    expires_at: datetime


class TokenManager:
    """Issue HS256 tokens for a single API issuer/audience pair."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue_access(self, user_id: uuid.UUID) -> IssuedToken:
        return self._issue(user_id, "access", self._access_ttl)

    def issue_refresh(self, user_id: uuid.UUID) -> IssuedToken:
        return self._issue(user_id, "refresh", self._refresh_ttl)

    def decode_access(self, token: str) -> TokenClaims:
        return self._decode(token, "access")

    def decode_refresh(self, token: str) -> TokenClaims:
        return self._decode(token, "refresh")

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _issue(self, user_id: uuid.UUID, token_type: Literal["access", "refresh"], ttl: timedelta) -> IssuedToken:
        issued_at = self._clock().astimezone(UTC)
        expires_at = issued_at + ttl
        token_id = uuid.uuid4()
        payload = {
            "sub": str(user_id),
            "jti": str(token_id),
            "type": token_type,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
        }
        return IssuedToken(
            value=jwt.encode(payload, self._secret, algorithm="HS256"),
            token_id=token_id,
            expires_at=expires_at,
        )

    def _decode(self, token: str, expected_type: Literal["access", "refresh"]) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["sub", "jti", "type", "iss", "aud", "iat", "nbf", "exp"]},
            )
            if payload["type"] != expected_type:
                raise TokenValidationError("unexpected token type")
            return TokenClaims(
                subject=uuid.UUID(payload["sub"]),
                token_id=uuid.UUID(payload["jti"]),
                token_type=expected_type,
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
            if isinstance(error, TokenValidationError):
                raise
            raise TokenValidationError("token validation failed") from error
