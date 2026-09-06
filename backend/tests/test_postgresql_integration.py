"""End-to-end API verification against migrated PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect

from reconcileflow.api import APISettings, create_app


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
        }
        assert expected_tables <= set(inspect(app.state.database.engine).get_table_names())

        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            ready = await client.get("/api/v1/health/ready")
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

        assert ready.status_code == 200
        assert created.status_code == 201
        assert executed.status_code == 200
        assert executed.json()["status"] == "SUCCEEDED"
        assert results.json()["total"] == 8
        assert audit.json()["items"][-1]["event_type"] == "RUN_SUCCEEDED"
    finally:
        app.state.database.dispose()
