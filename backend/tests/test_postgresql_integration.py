"""End-to-end API verification against migrated PostgreSQL."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import OrganizationMembershipRecord


DATABASE_URL = os.getenv("RECONCILEFLOW_TEST_POSTGRESQL_URL")
SAMPLES = Path(__file__).parents[2] / "data" / "sample"

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(not DATABASE_URL, reason="RECONCILEFLOW_TEST_POSTGRESQL_URL is not configured"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_migrated_postgresql_supports_complete_api_workflow(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=DATABASE_URL,
        upload_directory=tmp_path / "uploads",
        _env_file=None,
    ))
    try:
        expected_tables = {
            "alembic_version",
            "audit_events",
            "configuration_snapshots",
            "reconciliation_results",
            "reconciliation_runs",
            "source_files",
            "organizations",
            "organization_memberships",
            "users",
            "refresh_tokens",
        }
        assert expected_tables <= set(inspect(app.state.database.engine).get_table_names())

        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            ready = await client.get("/api/v1/health/ready")
            email = f"integration-{uuid.uuid4().hex}@example.com"
            registered = await client.post("/api/v1/auth/register", json={
                "email": email,
                "password": "correct horse battery staple",
                "organization_name": "Integration Test Organization",
            })
            logged_in = await client.post("/api/v1/auth/login", json={
                "email": email.upper(),
                "password": "correct horse battery staple",
            })
            access_token = logged_in.json()["access_token"]
            refresh_token = logged_in.json()["refresh_token"]
            current_user = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
            )
            refreshed = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
            )
            logged_out = await client.post(
                "/api/v1/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]}
            )
            client.headers["Authorization"] = f"Bearer {access_token}"
            client.headers["X-Organization-ID"] = registered.json()["membership"]["organization"]["id"]
            secondary_email = f"member-{uuid.uuid4().hex}@example.com"
            secondary = await client.post("/api/v1/auth/register", json={
                "email": secondary_email,
                "password": "correct horse battery staple",
                "organization_name": "Secondary Integration Organization",
            })
            members_path = f"/api/v1/organizations/{client.headers['X-Organization-ID']}/members"
            member_added = await client.post(
                members_path, json={"email": secondary_email, "role": "VIEWER"}
            )
            member_updated = await client.patch(
                f"{members_path}/{member_added.json()['id']}", json={"role": "ANALYST"}
            )
            member_removed = await client.delete(f"{members_path}/{member_added.json()['id']}")
            created = await client.post("/api/v1/reconciliation-runs", json={})
            run_id = created.json()["id"]
            for source_type, filename in (
                ("BANK_TRANSACTIONS", "bank_transactions.csv"),
                ("ERP_INVOICES", "erp_invoices.csv"),
                ("GATEWAY_SETTLEMENTS", "gateway_settlements.csv"),
            ):
                uploaded = await client.post(
                    f"/api/v1/reconciliation-runs/{run_id}/files",
                    data={"source_type": source_type},
                    files={"file": (filename, (SAMPLES / filename).read_bytes(), "application/octet-stream")},
                )
                assert uploaded.status_code == 201
            executed = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
            results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results")
            audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events")
            with app.state.database.session() as session:
                membership = session.scalar(
                    select(OrganizationMembershipRecord).where(
                        OrganizationMembershipRecord.organization_id == uuid.UUID(
                            client.headers["X-Organization-ID"]
                        )
                    )
                )
                membership.role = "VIEWER"
                session.commit()
            viewer_write = await client.post("/api/v1/reconciliation-runs", json={})
            viewer_read = await client.get(f"/api/v1/reconciliation-runs/{run_id}")

        assert ready.status_code == 200
        assert registered.status_code == 201
        assert registered.json()["membership"]["role"] == "OWNER"
        assert logged_in.status_code == 200
        assert logged_in.json()["authenticated"] is True
        assert current_user.status_code == 200
        assert current_user.json()["user"]["email"] == email
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] != refresh_token
        assert logged_out.status_code == 204
        assert secondary.status_code == member_added.status_code == 201
        assert member_updated.status_code == 200
        assert member_updated.json()["role"] == "ANALYST"
        assert member_removed.status_code == 204
        assert created.status_code == 201
        assert executed.status_code == 200
        assert executed.json()["status"] == "SUCCEEDED"
        assert results.json()["total"] == 8
        assert audit.json()["items"][-1]["event_type"] == "RUN_SUCCEEDED"
        assert viewer_write.status_code == 403
        assert viewer_write.json()["error"]["code"] == "INSUFFICIENT_ROLE"
        assert viewer_read.status_code == 200
    finally:
        app.state.database.dispose()
