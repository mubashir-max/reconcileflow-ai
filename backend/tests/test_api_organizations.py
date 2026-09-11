"""Organization discovery and profile management API behavior."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, OrganizationRecord


PASSWORD = "correct horse battery staple"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def organization_app(tmp_path):
    app = create_app(
        APISettings(
            environment="test",
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'organizations.db').as_posix()}",
            _env_file=None,
        )
    )
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _register(client: AsyncClient, name: str) -> dict:
    email = f"{name}@example.com"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "organization_name": f"{name.title()} Organization"},
    )
    assert registered.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {
        "email": email,
        "token": login.json()["access_token"],
        "organization_id": registered.json()["membership"]["organization"]["id"],
    }


def _headers(identity: dict, organization_id: str | None = None, *, select: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {identity['token']}"}
    if select:
        headers["X-Organization-ID"] = organization_id or identity["organization_id"]
    return headers


def _path(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}"


async def _add_member(client: AsyncClient, owner: dict, member: dict, role: str):
    return await client.post(
        f"{_path(owner['organization_id'])}/members",
        headers=_headers(owner),
        json={"email": member["email"], "role": role},
    )


@pytest.mark.anyio
async def test_authenticated_user_can_discover_and_read_organization_profile(organization_app):
    async with AsyncClient(transport=ASGITransport(app=organization_app), base_url="http://test") as client:
        owner = await _register(client, "profile-owner")
        listing = await client.get("/api/v1/organizations", headers=_headers(owner, select=False))
        profile = await client.get(_path(owner["organization_id"]), headers=_headers(owner))

    assert listing.status_code == profile.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == owner["organization_id"]
    assert listing.json()["items"][0]["role"] == "OWNER"
    assert profile.json()["current_user_role"] == "OWNER"
    assert "password" not in listing.text.lower()
    assert "token" not in profile.text.lower()


@pytest.mark.anyio
async def test_owner_can_manage_storage_quota_and_members_can_read_usage(organization_app):
    async with AsyncClient(transport=ASGITransport(app=organization_app), base_url="http://test") as client:
        owner = await _register(client, "quota-owner")
        organization_id = owner["organization_id"]
        updated = await client.patch(
            f"{_path(organization_id)}/storage-quota",
            headers=_headers(owner),
            json={"quota_bytes": 2048},
        )
        usage = await client.get(f"{_path(organization_id)}/storage-usage", headers=_headers(owner))

    assert updated.status_code == 200
    assert usage.status_code == 200
    assert usage.json() == {
        "organization_id": organization_id,
        "used_bytes": 0,
        "quota_bytes": 2048,
        "remaining_bytes": 2048,
        "utilization_percent": 0.0,
    }


@pytest.mark.anyio
async def test_owner_and_admin_can_update_name_without_changing_identity(organization_app):
    async with AsyncClient(transport=ASGITransport(app=organization_app), base_url="http://test") as client:
        owner = await _register(client, "update-owner")
        admin = await _register(client, "update-admin")
        assert (await _add_member(client, owner, admin, "ADMIN")).status_code == 201
        original = (await client.get(_path(owner["organization_id"]), headers=_headers(owner))).json()
        owner_update = await client.patch(
            _path(owner["organization_id"]), headers=_headers(owner), json={"name": "  Owner Renamed  "}
        )
        admin_update = await client.patch(
            _path(owner["organization_id"]),
            headers=_headers(admin, owner["organization_id"]),
            json={"name": "Admin Renamed"},
        )
        immutable = await client.patch(
            _path(owner["organization_id"]),
            headers=_headers(owner),
            json={"name": "Rejected", "slug": "changed"},
        )

    assert owner_update.status_code == admin_update.status_code == 200
    assert owner_update.json()["name"] == "Owner Renamed"
    assert admin_update.json()["name"] == "Admin Renamed"
    assert admin_update.json()["id"] == original["id"]
    assert admin_update.json()["slug"] == original["slug"]
    assert immutable.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["ANALYST", "VIEWER"])
async def test_non_manager_roles_cannot_update_organization(organization_app, role):
    async with AsyncClient(transport=ASGITransport(app=organization_app), base_url="http://test") as client:
        owner = await _register(client, f"{role.lower()}-profile-owner")
        member = await _register(client, f"{role.lower()}-profile-member")
        assert (await _add_member(client, owner, member, role)).status_code == 201
        denied = await client.patch(
            _path(owner["organization_id"]),
            headers=_headers(member, owner["organization_id"]),
            json={"name": "Not Allowed"},
        )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.anyio
async def test_cross_organization_and_inactive_organization_access_is_denied(organization_app):
    async with AsyncClient(transport=ASGITransport(app=organization_app), base_url="http://test") as client:
        first = await _register(client, "profile-first")
        second = await _register(client, "profile-second")
        cross = await client.get(_path(second["organization_id"]), headers=_headers(first))
        with organization_app.state.database.session() as session:
            organization = session.get(OrganizationRecord, uuid.UUID(first["organization_id"]))
            organization.is_active = False
            session.commit()
        inactive_profile = await client.get(_path(first["organization_id"]), headers=_headers(first))
        inactive_listing = await client.get("/api/v1/organizations", headers=_headers(first, select=False))

    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"
    assert inactive_profile.status_code == 403
    assert inactive_listing.status_code == 200
    assert inactive_listing.json() == {"items": [], "total": 0}


def test_openapi_documents_organization_profile_permissions(organization_app):
    paths = organization_app.openapi()["paths"]
    assert "No organization header" in paths["/api/v1/organizations"]["get"]["description"]
    operations = paths["/api/v1/organizations/{organization_id}"]
    assert "active membership" in operations["get"]["description"]
    assert "OWNER or ADMIN" in operations["patch"]["description"]
