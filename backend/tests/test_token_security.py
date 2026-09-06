from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from reconcileflow.auth import TokenManager, TokenValidationError


def _manager(secret: str = "s" * 32) -> TokenManager:
    return TokenManager(
        secret=secret,
        issuer="test-issuer",
        audience="test-audience",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=30),
    )


def test_access_and_refresh_tokens_have_strict_types() -> None:
    manager = _manager()
    user_id = uuid.uuid4()
    access = manager.issue_access(user_id)
    refresh = manager.issue_refresh(user_id)

    assert manager.decode_access(access.value).subject == user_id
    assert manager.decode_refresh(refresh.value).subject == user_id
    with pytest.raises(TokenValidationError):
        manager.decode_refresh(access.value)
    with pytest.raises(TokenValidationError):
        manager.decode_access(refresh.value)


def test_modified_or_wrongly_signed_token_is_rejected() -> None:
    access = _manager().issue_access(uuid.uuid4()).value
    with pytest.raises(TokenValidationError):
        _manager("x" * 32).decode_access(access)
    with pytest.raises(TokenValidationError):
        _manager().decode_access(access[:-1] + ("a" if access[-1] != "a" else "b"))


def test_expired_token_is_rejected() -> None:
    manager = TokenManager(
        secret="s" * 32,
        issuer="test-issuer",
        audience="test-audience",
        access_ttl=timedelta(seconds=-1),
        refresh_ttl=timedelta(days=1),
    )
    with pytest.raises(TokenValidationError):
        manager.decode_access(manager.issue_access(uuid.uuid4()).value)


def test_refresh_hash_is_deterministic_and_does_not_contain_token() -> None:
    token = _manager().issue_refresh(uuid.uuid4()).value
    digest = TokenManager.hash_refresh_token(token)
    assert len(digest) == 64
    assert token not in digest
    assert digest == TokenManager.hash_refresh_token(token)
