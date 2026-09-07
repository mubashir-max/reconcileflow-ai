"""End-to-end organization isolation at the API boundary."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tenant_app(tmp_path):
    app = create_app(
        APISettings(
            environment="test",
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'tenants.db').as_posix()}",
            upload_directory=tmp_path / "uploads",
            _env_file=None,
        )
    )
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _identity(client: AsyncClient, name: str) -> tuple[str, str]:
    email = f"{name}@example.com"
    password = "correct horse battery staple"
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "organization_name": f"{name.title()} Finance"},
    )
    assert registration.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.json()["access_token"], registration.json()["membership"]["organization"]["id"]


def _headers(token: str, organization_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": organization_id}


@pytest.mark.anyio
async def test_organization_header_and_active_membership_are_required(tenant_app):
    async with AsyncClient(transport=ASGITransport(app=tenant_app, raise_app_exceptions=False), base_url="http://test") as client:
        first_token, first_organization = await _identity(client, "first")
        _, second_organization = await _identity(client, "second")
        missing = await client.get(
            "/api/v1/reconciliation-runs",
            headers={"Authorization": f"Bearer {first_token}"},
        )
        invalid = await client.get(
            "/api/v1/reconciliation-runs",
            headers={"Authorization": f"Bearer {first_token}", "X-Organization-ID": "not-a-uuid"},
        )
        denied = await client.get(
            "/api/v1/reconciliation-runs",
            headers=_headers(first_token, second_organization),
        )
    assert (missing.status_code, missing.json()["error"]["code"]) == (400, "ORGANIZATION_REQUIRED")
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (400, "INVALID_ORGANIZATION")
    assert (denied.status_code, denied.json()["error"]["code"]) == (403, "ORGANIZATION_ACCESS_DENIED")
    assert first_organization != second_organization


@pytest.mark.anyio
async def test_runs_and_files_are_isolated_between_organizations(tenant_app):
    async with AsyncClient(transport=ASGITransport(app=tenant_app, raise_app_exceptions=False), base_url="http://test") as client:
        first_token, first_organization = await _identity(client, "alpha")
        second_token, second_organization = await _identity(client, "beta")
        first_headers = _headers(first_token, first_organization)
        second_headers = _headers(second_token, second_organization)

        first_run = await client.post("/api/v1/reconciliation-runs", json={}, headers=first_headers)
        second_run = await client.post("/api/v1/reconciliation-runs", json={}, headers=second_headers)
        first_run_id = first_run.json()["id"]
        uploaded = await client.post(
            f"/api/v1/reconciliation-runs/{first_run_id}/files",
            headers=first_headers,
            data={"source_type": "BANK_TRANSACTIONS"},
            files={"file": ("bank.csv", b"id,amount\n1,10.00\n", "text/csv")},
        )

        first_listing = await client.get("/api/v1/reconciliation-runs", headers=first_headers)
        second_listing = await client.get("/api/v1/reconciliation-runs", headers=second_headers)
        hidden_run = await client.get(f"/api/v1/reconciliation-runs/{first_run_id}", headers=second_headers)
        hidden_file = await client.get(f"/api/v1/files/{uploaded.json()['id']}", headers=second_headers)
        hidden_results = await client.get(f"/api/v1/reconciliation-runs/{first_run_id}/results", headers=second_headers)
        hidden_audit = await client.get(f"/api/v1/reconciliation-runs/{first_run_id}/audit-events", headers=second_headers)
        hidden_execution = await client.post(f"/api/v1/reconciliation-runs/{first_run_id}/execute", headers=second_headers)

    assert first_run.status_code == second_run.status_code == uploaded.status_code == 201
    assert [item["id"] for item in first_listing.json()["items"]] == [first_run_id]
    assert [item["id"] for item in second_listing.json()["items"]] == [second_run.json()["id"]]
    assert all(response.status_code == 404 for response in (
        hidden_run, hidden_file, hidden_results, hidden_audit, hidden_execution
    ))


def test_openapi_documents_organization_header(tenant_app):
    operation = tenant_app.openapi()["paths"]["/api/v1/reconciliation-runs"]["get"]
    organization_header = next(item for item in operation["parameters"] if item["name"] == "X-Organization-ID")
    assert organization_header["in"] == "header"
    assert organization_header["required"] is False
