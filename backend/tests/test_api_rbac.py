"""Role-based access control for organization reconciliation operations."""

from __future__ import annotations

from pathlib import Path
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, OrganizationMembershipRecord


SAMPLES = Path(__file__).parents[2] / "data" / "sample"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def rbac_app(tmp_path):
    app = create_app(
        APISettings(
            environment="test",
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'rbac.db').as_posix()}",
            upload_directory=tmp_path / "uploads",
            _env_file=None,
        )
    )
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _registered_client(client: AsyncClient) -> tuple[dict[str, str], str]:
    email = "roles@example.com"
    password = "correct horse battery staple"
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "organization_name": "Roles Finance"},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    organization_id = registration.json()["membership"]["organization"]["id"]
    return {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Organization-ID": organization_id,
    }, organization_id


def _set_role(app, organization_id: str, role: str, *, active: bool = True) -> None:
    with app.state.database.session() as session:
        membership = session.scalar(
            select(OrganizationMembershipRecord).where(
                OrganizationMembershipRecord.organization_id == uuid.UUID(organization_id)
            )
        )
        membership.role = role
        membership.is_active = active
        session.commit()


async def _upload(client: AsyncClient, headers: dict[str, str], run_id: str, source_type: str, filename: str):
    return await client.post(
        f"/api/v1/reconciliation-runs/{run_id}/files",
        headers=headers,
        data={"source_type": source_type},
        files={"file": (filename, (SAMPLES / filename).read_bytes(), "application/octet-stream")},
    )


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "ANALYST"])
async def test_operator_roles_can_create_upload_execute_and_read(rbac_app, role):
    async with AsyncClient(transport=ASGITransport(app=rbac_app, raise_app_exceptions=False), base_url="http://test") as client:
        headers, organization_id = await _registered_client(client)
        _set_role(rbac_app, organization_id, role)
        created = await client.post("/api/v1/reconciliation-runs", headers=headers, json={})
        run_id = created.json()["id"]
        bank = await _upload(client, headers, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        erp = await _upload(client, headers, run_id, "ERP_INVOICES", "erp_invoices.csv")
        executed = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute", headers=headers)
        retrieved = await client.get(f"/api/v1/reconciliation-runs/{run_id}", headers=headers)
    assert created.status_code == bank.status_code == erp.status_code == 201
    assert executed.status_code == 202
    assert retrieved.status_code == 200


@pytest.mark.anyio
async def test_viewer_can_read_but_cannot_create_upload_or_execute(rbac_app):
    async with AsyncClient(transport=ASGITransport(app=rbac_app, raise_app_exceptions=False), base_url="http://test") as client:
        headers, organization_id = await _registered_client(client)
        existing = await client.post("/api/v1/reconciliation-runs", headers=headers, json={})
        run_id = existing.json()["id"]
        _set_role(rbac_app, organization_id, "VIEWER")

        listing = await client.get("/api/v1/reconciliation-runs", headers=headers)
        retrieved = await client.get(f"/api/v1/reconciliation-runs/{run_id}", headers=headers)
        files = await client.get(f"/api/v1/reconciliation-runs/{run_id}/files", headers=headers)
        results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results", headers=headers)
        audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events", headers=headers)
        create_denied = await client.post("/api/v1/reconciliation-runs", headers=headers, json={})
        upload_denied = await client.post(
            f"/api/v1/reconciliation-runs/{run_id}/files",
            headers=headers,
            data={"source_type": "BANK_TRANSACTIONS"},
            files={"file": ("bank.csv", b"id,amount\n1,10.00\n", "text/csv")},
        )
        execution_denied = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute", headers=headers)

    assert all(response.status_code == 200 for response in (listing, retrieved, files, results, audit))
    for response in (create_denied, upload_denied, execution_denied):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.anyio
async def test_inactive_membership_cannot_read_or_write(rbac_app):
    async with AsyncClient(transport=ASGITransport(app=rbac_app, raise_app_exceptions=False), base_url="http://test") as client:
        headers, organization_id = await _registered_client(client)
        _set_role(rbac_app, organization_id, "OWNER", active=False)
        read = await client.get("/api/v1/reconciliation-runs", headers=headers)
        write = await client.post("/api/v1/reconciliation-runs", headers=headers, json={})
    for response in (read, write):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ORGANIZATION_ACCESS_DENIED"


def test_openapi_describes_roles_for_write_operations(rbac_app):
    schema = rbac_app.openapi()["paths"]
    for path in (
        "/api/v1/reconciliation-runs",
        "/api/v1/reconciliation-runs/{run_id}/files",
        "/api/v1/reconciliation-runs/{run_id}/execute",
    ):
        description = schema[path]["post"]["description"]
        assert all(role in description for role in ("OWNER", "ADMIN", "ANALYST"))
