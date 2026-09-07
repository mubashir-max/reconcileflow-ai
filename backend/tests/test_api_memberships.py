"""Organization membership management API behavior and authorization."""

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
def membership_app(tmp_path):
    app = create_app(
        APISettings(
            environment="test",
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'memberships.db').as_posix()}",
            _env_file=None,
        )
    )
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _register(client: AsyncClient, name: str) -> dict:
    email = f"{name}@example.com"
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "organization_name": f"{name.title()} Organization"},
    )
    assert registration.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {
        "email": email,
        "token": login.json()["access_token"],
        "organization_id": registration.json()["membership"]["organization"]["id"],
    }


def _headers(identity: dict, organization_id: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {identity['token']}",
        "X-Organization-ID": organization_id or identity["organization_id"],
    }


def _members_path(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/members"


async def _add(client: AsyncClient, owner: dict, target: dict, role: str):
    return await client.post(
        _members_path(owner["organization_id"]),
        headers=_headers(owner),
        json={"email": target["email"].upper(), "role": role},
    )


@pytest.mark.anyio
async def test_owner_can_add_list_update_and_deactivate_existing_user(membership_app):
    async with AsyncClient(transport=ASGITransport(app=membership_app, raise_app_exceptions=False), base_url="http://test") as client:
        owner = await _register(client, "owner")
        target = await _register(client, "member")
        added = await _add(client, owner, target, "VIEWER")
        membership_id = added.json()["id"]
        listing = await client.get(_members_path(owner["organization_id"]), headers=_headers(owner))
        updated = await client.patch(
            f"{_members_path(owner['organization_id'])}/{membership_id}",
            headers=_headers(owner),
            json={"role": "ANALYST"},
        )
        removed = await client.delete(
            f"{_members_path(owner['organization_id'])}/{membership_id}", headers=_headers(owner)
        )

    assert added.status_code == 201
    assert added.json()["user"]["email"] == target["email"]
    assert added.json()["role"] == "VIEWER"
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert updated.status_code == 200
    assert updated.json()["role"] == "ANALYST"
    assert removed.status_code == 204
    assert "password" not in added.text.lower()
    assert "token" not in listing.text.lower()


@pytest.mark.anyio
async def test_duplicate_unknown_and_cross_organization_memberships_are_safe(membership_app):
    async with AsyncClient(transport=ASGITransport(app=membership_app, raise_app_exceptions=False), base_url="http://test") as client:
        owner = await _register(client, "safe-owner")
        target = await _register(client, "safe-member")
        assert (await _add(client, owner, target, "VIEWER")).status_code == 201
        duplicate = await _add(client, owner, target, "ANALYST")
        unknown = await client.post(
            _members_path(owner["organization_id"]),
            headers=_headers(owner),
            json={"email": "missing@example.com", "role": "VIEWER"},
        )
        cross_organization = await client.get(
            _members_path(target["organization_id"]), headers=_headers(owner)
        )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "PERSISTENCE_CONFLICT"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "USER_NOT_FOUND"
    assert cross_organization.status_code == 403
    assert cross_organization.json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"


@pytest.mark.anyio
async def test_admin_can_manage_non_owners_but_cannot_manage_owner_role(membership_app):
    async with AsyncClient(transport=ASGITransport(app=membership_app, raise_app_exceptions=False), base_url="http://test") as client:
        owner = await _register(client, "admin-owner")
        admin = await _register(client, "admin-user")
        analyst = await _register(client, "admin-target")
        owner_membership = (await client.get(_members_path(owner["organization_id"]), headers=_headers(owner))).json()["items"][0]
        admin_membership = await _add(client, owner, admin, "ADMIN")
        admin_headers = _headers(admin, owner["organization_id"])
        allowed = await client.post(
            _members_path(owner["organization_id"]),
            headers=admin_headers,
            json={"email": analyst["email"], "role": "ANALYST"},
        )
        promote_owner = await client.patch(
            f"{_members_path(owner['organization_id'])}/{allowed.json()['id']}",
            headers=admin_headers,
            json={"role": "OWNER"},
        )
        demote_owner = await client.patch(
            f"{_members_path(owner['organization_id'])}/{owner_membership['id']}",
            headers=admin_headers,
            json={"role": "ADMIN"},
        )
        remove_owner = await client.delete(
            f"{_members_path(owner['organization_id'])}/{owner_membership['id']}", headers=admin_headers
        )

    assert admin_membership.status_code == allowed.status_code == 201
    for response in (promote_owner, demote_owner, remove_owner):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "OWNER_ROLE_REQUIRED"


@pytest.mark.anyio
async def test_final_owner_cannot_be_demoted_or_removed(membership_app):
    async with AsyncClient(transport=ASGITransport(app=membership_app, raise_app_exceptions=False), base_url="http://test") as client:
        owner = await _register(client, "final-owner")
        owner_membership = (await client.get(_members_path(owner["organization_id"]), headers=_headers(owner))).json()["items"][0]
        path = f"{_members_path(owner['organization_id'])}/{owner_membership['id']}"
        demoted = await client.patch(path, headers=_headers(owner), json={"role": "ADMIN"})
        removed = await client.delete(path, headers=_headers(owner))
    for response in (demoted, removed):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "FINAL_OWNER_REQUIRED"


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["ANALYST", "VIEWER"])
async def test_analyst_and_viewer_cannot_manage_memberships(membership_app, role):
    async with AsyncClient(transport=ASGITransport(app=membership_app, raise_app_exceptions=False), base_url="http://test") as client:
        owner = await _register(client, f"{role.lower()}-owner")
        member = await _register(client, f"{role.lower()}-member")
        assert (await _add(client, owner, member, role)).status_code == 201
        denied = await client.get(
            _members_path(owner["organization_id"]), headers=_headers(member, owner["organization_id"])
        )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.anyio
async def test_deactivated_member_loses_organization_access(membership_app):
    async with AsyncClient(transport=ASGITransport(app=membership_app, raise_app_exceptions=False), base_url="http://test") as client:
        owner = await _register(client, "inactive-owner")
        member = await _register(client, "inactive-member")
        added = await _add(client, owner, member, "VIEWER")
        await client.delete(
            f"{_members_path(owner['organization_id'])}/{added.json()['id']}", headers=_headers(owner)
        )
        denied = await client.get(
            "/api/v1/reconciliation-runs", headers=_headers(member, owner["organization_id"])
        )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"


def test_openapi_documents_membership_management_permissions(membership_app):
    operations = membership_app.openapi()["paths"][_members_path("{organization_id}")]
    assert "OWNER or ADMIN" in operations["get"]["description"]
    assert "Only OWNER" in operations["post"]["description"]
