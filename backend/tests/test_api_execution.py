from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base


SAMPLES = Path(__file__).parents[2] / "data" / "sample"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def execution_app(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'execution.db').as_posix()}",
        upload_directory=tmp_path / "uploads",
        _env_file=None,
    ))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _create_run(client):
    response = await client.post("/api/v1/reconciliation-runs", json={})
    assert response.status_code == 201
    return response.json()["id"]


async def _upload(client, run_id, source_type, filename):
    response = await client.post(
        f"/api/v1/reconciliation-runs/{run_id}/files",
        data={"source_type": source_type},
        files={"file": (filename, (SAMPLES / filename).read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 201


@pytest.mark.anyio
async def test_execute_persists_results_and_ordered_audit_history(execution_app):
    async with AsyncClient(transport=ASGITransport(app=execution_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        await _upload(client, run_id, "GATEWAY_SETTLEMENTS", "gateway_settlements.csv")

        executed = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
        run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")
        results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results?limit=3")
        review = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results?requires_review=true")
        exact = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results?status=EXACT_MATCH")
        audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events")

    assert executed.status_code == 200
    assert executed.json() == {"run_id": run_id, "status": "SUCCEEDED", "result_count": 8, "results_requiring_review": 3}
    assert run.json()["status"] == "SUCCEEDED"
    assert results.json()["total"] == 8
    assert len(results.json()["items"]) == 3
    assert review.json()["total"] == 3
    assert exact.json()["total"] == 1
    sequences = [item["sequence_number"] for item in audit.json()["items"]]
    assert sequences == list(range(1, len(sequences) + 1))
    assert audit.json()["items"][-1]["event_type"] == "RUN_SUCCEEDED"


@pytest.mark.anyio
async def test_execute_requires_bank_and_erp_files(execution_app):
    async with AsyncClient(transport=ASGITransport(app=execution_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        response = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
        run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_SOURCE_FILES"
    assert run.json()["status"] == "PENDING"


@pytest.mark.anyio
async def test_completed_run_cannot_execute_twice(execution_app):
    async with AsyncClient(transport=ASGITransport(app=execution_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        assert (await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")).status_code == 200
        repeated = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "RUN_NOT_PENDING"


@pytest.mark.anyio
async def test_invalid_source_fails_safely_without_partial_results(execution_app):
    async with AsyncClient(transport=ASGITransport(app=execution_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        for source_type, filename in (("BANK_TRANSACTIONS", "bad.csv"), ("ERP_INVOICES", "bad-erp.csv")):
            response = await client.post(
                f"/api/v1/reconciliation-runs/{run_id}/files",
                data={"source_type": source_type},
                files={"file": (filename, b"id,amount\n1,10\n", "text/csv")},
            )
            assert response.status_code == 201
        failed = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
        run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")
        results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results")
        audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events")
    assert failed.status_code == 422
    assert failed.json()["error"]["message"] == "Reconciliation execution failed. Check the source files and configuration."
    assert run.json()["status"] == "FAILED"
    assert run.json()["error_message"] == "Reconciliation execution failed."
    assert results.json()["total"] == 0
    assert audit.json()["items"][-1]["event_type"] == "RUN_FAILED"
