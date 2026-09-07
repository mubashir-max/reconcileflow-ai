"""Security audit recording, secrecy, authorization, and tenant isolation."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base


PASSWORD = "correct horse battery staple"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def audit_app(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'security-audit.db').as_posix()}",
        _env_file=None,
    ))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _register(client: AsyncClient, name: str) -> dict:
    email = f"{name}@example.com"
    registered = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": PASSWORD,
        "organization_name": f"{name.title()} Organization",
    })
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {
        "email": email,
        "organization_id": registered.json()["membership"]["organization"]["id"],
        "access_token": login.json()["access_token"],
        "refresh_token": login.json()["refresh_token"],
    }


def _headers(identity: dict, organization_id: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {identity['access_token']}",
        "X-Organization-ID": organization_id or identity["organization_id"],
    }


def _audit_path(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/security-audit-events"


@pytest.mark.anyio
async def test_security_events_cover_authentication_profile_and_membership_actions(audit_app):
    async with AsyncClient(transport=ASGITransport(app=audit_app), base_url="http://test") as client:
        owner = await _register(client, "audit-owner")
        member = await _register(client, "audit-member")
        organization_id = owner["organization_id"]
        headers = _headers(owner)
        await client.patch(
            f"/api/v1/organizations/{organization_id}", headers=headers, json={"name": "Audited Organization"}
        )
        added = await client.post(
            f"/api/v1/organizations/{organization_id}/members",
            headers=headers,
            json={"email": member["email"], "role": "VIEWER"},
        )
        await client.patch(
            f"/api/v1/organizations/{organization_id}/members/{added.json()['id']}",
            headers=headers,
            json={"role": "ANALYST"},
        )
        await client.delete(
            f"/api/v1/organizations/{organization_id}/members/{added.json()['id']}", headers=headers
        )
        refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": owner["refresh_token"]})
        await client.post("/api/v1/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]})
        audit = await client.get(_audit_path(organization_id), headers=headers)

    assert audit.status_code == 200
    event_types = {item["event_type"] for item in audit.json()["items"]}
    assert event_types >= {
        "USER_REGISTERED", "USER_LOGGED_IN", "REFRESH_TOKEN_ROTATED", "USER_LOGGED_OUT",
        "ORGANIZATION_PROFILE_UPDATED", "MEMBERSHIP_CREATED", "MEMBERSHIP_ROLE_CHANGED",
        "MEMBERSHIP_DEACTIVATED",
    }
    serialized = audit.text.lower()
    assert PASSWORD not in serialized
    assert owner["access_token"].lower() not in serialized
    assert owner["refresh_token"].lower() not in serialized


@pytest.mark.anyio
async def test_security_audit_requires_manager_role_and_selected_tenant(audit_app):
    async with AsyncClient(transport=ASGITransport(app=audit_app), base_url="http://test") as client:
        owner = await _register(client, "permissions-owner")
        outsider = await _register(client, "permissions-outsider")
        member = await _register(client, "permissions-viewer")
        added = await client.post(
            f"/api/v1/organizations/{owner['organization_id']}/members",
            headers=_headers(owner),
            json={"email": member["email"], "role": "VIEWER"},
        )
        assert added.status_code == 201
        viewer = await client.get(
            _audit_path(owner["organization_id"]), headers=_headers(member, owner["organization_id"])
        )
        cross_tenant = await client.get(
            _audit_path(outsider["organization_id"]), headers=_headers(owner)
        )

    assert viewer.status_code == 403
    assert viewer.json()["error"]["code"] == "INSUFFICIENT_ROLE"
    assert cross_tenant.status_code == 403
    assert cross_tenant.json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"


def test_openapi_documents_security_audit_permissions(audit_app):
    operation = audit_app.openapi()["paths"][
        "/api/v1/organizations/{organization_id}/security-audit-events"
    ]["get"]
    assert "OWNER or ADMIN" in operation["description"]
    assert "selected organization" in operation["description"]
