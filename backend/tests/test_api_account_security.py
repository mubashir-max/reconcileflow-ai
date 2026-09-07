"""Password changes and account-wide refresh-session revocation."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base


OLD_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a newer correct horse battery staple"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def account_app(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'account-security.db').as_posix()}",
        _env_file=None,
    ))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _identity(client: AsyncClient) -> dict:
    registration = await client.post("/api/v1/auth/register", json={
        "email": "owner@example.com",
        "password": OLD_PASSWORD,
        "organization_name": "Account Security Organization",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": "owner@example.com", "password": OLD_PASSWORD,
    })
    return {
        "organization_id": registration.json()["membership"]["organization"]["id"],
        **login.json(),
    }


def _headers(identity: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {identity['access_token']}",
        "X-Organization-ID": identity["organization_id"],
    }


@pytest.mark.anyio
async def test_password_change_replaces_password_and_revokes_refresh_sessions(account_app):
    async with AsyncClient(transport=ASGITransport(app=account_app), base_url="http://test") as client:
        identity = await _identity(client)
        changed = await client.post(
            "/api/v1/auth/change-password",
            headers=_headers(identity),
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )
        old_refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": identity["refresh_token"]}
        )
        old_login = await client.post("/api/v1/auth/login", json={
            "email": "owner@example.com", "password": OLD_PASSWORD,
        })
        new_login = await client.post("/api/v1/auth/login", json={
            "email": "owner@example.com", "password": NEW_PASSWORD,
        })
        current_access = await client.get("/api/v1/auth/me", headers=_headers(identity))
        audit = await client.get(
            f"/api/v1/organizations/{identity['organization_id']}/security-audit-events",
            headers=_headers(identity),
        )

    assert changed.status_code == 204
    assert old_refresh.status_code == 401
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert current_access.status_code == 200
    assert "PASSWORD_CHANGED" in {item["event_type"] for item in audit.json()["items"]}
    assert OLD_PASSWORD not in audit.text
    assert NEW_PASSWORD not in audit.text
    assert identity["refresh_token"] not in audit.text


@pytest.mark.anyio
async def test_password_change_rejects_wrong_reused_and_invalid_passwords(account_app):
    async with AsyncClient(transport=ASGITransport(app=account_app), base_url="http://test") as client:
        identity = await _identity(client)
        wrong = await client.post(
            "/api/v1/auth/change-password", headers=_headers(identity),
            json={"current_password": "wrong password", "new_password": NEW_PASSWORD},
        )
        reused = await client.post(
            "/api/v1/auth/change-password", headers=_headers(identity),
            json={"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
        )
        weak = await client.post(
            "/api/v1/auth/change-password", headers=_headers(identity),
            json={"current_password": OLD_PASSWORD, "new_password": "short"},
        )

    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "PASSWORD_REUSE"
    assert weak.status_code == 422


@pytest.mark.anyio
async def test_revoke_all_sessions_invalidates_every_refresh_token(account_app):
    async with AsyncClient(transport=ASGITransport(app=account_app), base_url="http://test") as client:
        first = await _identity(client)
        second_login = await client.post("/api/v1/auth/login", json={
            "email": "owner@example.com", "password": OLD_PASSWORD,
        })
        revoked = await client.delete("/api/v1/auth/sessions", headers=_headers(first))
        first_refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
        second_refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": second_login.json()["refresh_token"]}
        )
        audit = await client.get(
            f"/api/v1/organizations/{first['organization_id']}/security-audit-events",
            headers=_headers(first),
        )

    assert revoked.status_code == 204
    assert first_refresh.status_code == second_refresh.status_code == 401
    event = next(item for item in audit.json()["items"] if item["event_type"] == "ALL_SESSIONS_REVOKED")
    assert event["details"]["revoked_session_count"] == 2


def test_openapi_documents_password_and_session_security(account_app):
    paths = account_app.openapi()["paths"]
    assert "current password" in paths["/api/v1/auth/change-password"]["post"]["description"]
    assert "every refresh-token session" in paths["/api/v1/auth/sessions"]["delete"]["description"]
    assert "password_hash" not in str(account_app.openapi())
