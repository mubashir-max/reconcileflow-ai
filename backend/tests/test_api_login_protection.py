"""Persistent login attempt protection and temporary account lockout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, UserRecord


PASSWORD = "correct horse battery staple"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def protection_app(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'login-protection.db').as_posix()}",
        login_max_failed_attempts=3,
        login_lockout_minutes=15,
        _env_file=None,
    ))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _register_and_login(client: AsyncClient) -> dict:
    registered = await client.post("/api/v1/auth/register", json={
        "email": "owner@example.com",
        "password": PASSWORD,
        "organization_name": "Protected Organization",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": "owner@example.com", "password": PASSWORD,
    })
    return {
        "organization_id": registered.json()["membership"]["organization"]["id"],
        "access_token": login.json()["access_token"],
    }


async def _login(client: AsyncClient, password: str, email: str = "owner@example.com"):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


@pytest.mark.anyio
async def test_repeated_failures_lock_account_with_same_safe_response(protection_app):
    async with AsyncClient(transport=ASGITransport(app=protection_app), base_url="http://test") as client:
        identity = await _register_and_login(client)
        failures = [await _login(client, "incorrect password") for _ in range(3)]
        correct_while_locked = await _login(client, PASSWORD)
        unknown = await _login(client, "incorrect password", "unknown@example.com")
        audit = await client.get(
            f"/api/v1/organizations/{identity['organization_id']}/security-audit-events",
            headers={
                "Authorization": f"Bearer {identity['access_token']}",
                "X-Organization-ID": identity["organization_id"],
            },
        )

    expected = {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "The email or password is incorrect.",
            "details": [],
        }
    }
    assert all(response.status_code == 401 and response.json() == expected for response in failures)
    assert correct_while_locked.status_code == 401
    assert correct_while_locked.json() == unknown.json() == expected
    event_types = [item["event_type"] for item in audit.json()["items"]]
    assert event_types.count("LOGIN_FAILED") == 4
    assert event_types.count("ACCOUNT_TEMPORARILY_LOCKED") == 1
    assert PASSWORD not in audit.text
    assert "incorrect password" not in audit.text


@pytest.mark.anyio
async def test_login_succeeds_after_lockout_expires(protection_app):
    async with AsyncClient(transport=ASGITransport(app=protection_app), base_url="http://test") as client:
        await _register_and_login(client)
        for _ in range(3):
            await _login(client, "incorrect password")
        with protection_app.state.database.session() as session:
            user = session.scalar(select(UserRecord).where(UserRecord.email == "owner@example.com"))
            user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        successful = await _login(client, PASSWORD)

    assert successful.status_code == 200
    with protection_app.state.database.session() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.email == "owner@example.com"))
        assert user.failed_login_attempts == 0
        assert user.locked_until is None


@pytest.mark.anyio
async def test_successful_login_resets_failures_before_threshold(protection_app):
    async with AsyncClient(transport=ASGITransport(app=protection_app), base_url="http://test") as client:
        await _register_and_login(client)
        await _login(client, "incorrect password")
        await _login(client, "incorrect password")
        successful = await _login(client, PASSWORD)
        next_failure = await _login(client, "incorrect password")

    assert successful.status_code == 200
    assert next_failure.status_code == 401
    with protection_app.state.database.session() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.email == "owner@example.com"))
        assert user.failed_login_attempts == 1
        assert user.locked_until is None


def test_openapi_keeps_lockout_details_private(protection_app):
    operation = protection_app.openapi()["paths"]["/api/v1/auth/login"]["post"]
    assert operation["responses"]["401"]["description"] == "The supplied credentials are invalid."
