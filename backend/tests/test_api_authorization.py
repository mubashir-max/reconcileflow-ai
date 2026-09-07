"""Authorization boundaries for public and protected API routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def authorization_app(tmp_path):
    app = create_app(
        APISettings(
            environment="test",
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'authorization.db').as_posix()}",
            upload_directory=tmp_path / "uploads",
            _env_file=None,
        )
    )
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _access_token(client: AsyncClient) -> tuple[str, str]:
    credentials = {
        "email": "protected@example.com",
        "password": "correct horse battery staple",
    }
    registered = await client.post(
        "/api/v1/auth/register",
        json={**credentials, "organization_name": "Protected Organization"},
    )
    assert registered.status_code == 201
    logged_in = await client.post("/api/v1/auth/login", json=credentials)
    assert logged_in.status_code == 200
    return logged_in.json()["access_token"], registered.json()["membership"]["organization"]["id"]


@pytest.mark.anyio
async def test_public_service_health_and_authentication_routes_remain_accessible(authorization_app):
    async with AsyncClient(
        transport=ASGITransport(app=authorization_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/api/v1/health/live")).status_code == 200
        assert (await client.get("/api/v1/health/ready")).status_code == 200
        token, organization_id = await _access_token(client)
        assert token
        assert organization_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/reconciliation-runs"),
        ("GET", "/api/v1/reconciliation-runs"),
        ("GET", "/api/v1/files/00000000-0000-0000-0000-000000000000"),
        ("POST", "/api/v1/reconciliation-runs/00000000-0000-0000-0000-000000000000/execute"),
        ("GET", "/api/v1/reconciliation-runs/00000000-0000-0000-0000-000000000000/results"),
        ("GET", "/api/v1/reconciliation-runs/00000000-0000-0000-0000-000000000000/audit-events"),
    ],
)
async def test_protected_route_groups_reject_missing_credentials(authorization_app, method, path):
    async with AsyncClient(
        transport=ASGITransport(app=authorization_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


@pytest.mark.anyio
async def test_protected_routes_reject_invalid_token_and_accept_valid_access_token(authorization_app):
    async with AsyncClient(
        transport=ASGITransport(app=authorization_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        invalid = await client.get(
            "/api/v1/reconciliation-runs",
            headers={"Authorization": "Bearer invalid-token"},
        )
        token, organization_id = await _access_token(client)
        created = await client.post(
            "/api/v1/reconciliation-runs",
            json={},
            headers={"Authorization": f"Bearer {token}", "X-Organization-ID": organization_id},
        )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"
    assert created.status_code == 201


def test_openapi_documents_bearer_security_for_protected_routes(authorization_app):
    schema = authorization_app.openapi()
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    for path in (
        "/api/v1/reconciliation-runs",
        "/api/v1/reconciliation-runs/{run_id}/files",
        "/api/v1/reconciliation-runs/{run_id}/execute",
        "/api/v1/reconciliation-runs/{run_id}/results",
        "/api/v1/reconciliation-runs/{run_id}/audit-events",
    ):
        for operation in schema["paths"][path].values():
            assert {"BearerAuth": []} in operation["security"]
    assert "security" not in schema["paths"]["/api/v1/health/live"]["get"]
    assert "security" not in schema["paths"]["/api/v1/auth/login"]["post"]
