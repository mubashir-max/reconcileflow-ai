from pathlib import Path
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.api.auth_dependencies import TenantContext, get_current_user, get_tenant_context
from reconcileflow.persistence import Base, BackgroundJobRecord, OrganizationRecord
from reconcileflow.storage import LocalFileStorage
from reconcileflow.worker import BackgroundWorker, ReconciliationJobProcessor


TEST_ORGANIZATION_ID = uuid.UUID("10000000-0000-0000-0000-000000000003")


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
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(TEST_ORGANIZATION_ID, uuid.uuid4(), "OWNER")
    with app.state.database.session() as session:
        session.add(OrganizationRecord(id=TEST_ORGANIZATION_ID, name="Execution Organization", slug="execution-organization"))
        session.commit()
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


def _worker(app, *, clock=None, retry_delay_seconds=30):
    return BackgroundWorker(
        session_provider=app.state.database.session,
        processor=ReconciliationJobProcessor(
            session_provider=app.state.database.session,
            storage=LocalFileStorage(
                app.state.settings.upload_directory,
                app.state.settings.max_upload_size_bytes,
            ),
        ),
        worker_id="execution-test-worker",
        retry_delay_seconds=retry_delay_seconds,
        clock=clock,
    )


@pytest.mark.anyio
async def test_execute_persists_results_and_ordered_audit_history(execution_app):
    async with AsyncClient(transport=ASGITransport(app=execution_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        await _upload(client, run_id, "GATEWAY_SETTLEMENTS", "gateway_settlements.csv")

        executed = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
        queued_run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")
        empty_results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results")
        assert _worker(execution_app).run_once() is True
        run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")
        results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results?limit=3")
        review = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results?requires_review=true")
        exact = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results?status=EXACT_MATCH")
        audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events")

    assert executed.status_code == 202
    assert executed.json()["run_id"] == run_id
    assert executed.json()["status"] == "QUEUED"
    assert executed.json()["job_id"]
    assert queued_run.json()["status"] == "PENDING"
    assert empty_results.json()["total"] == 0
    assert run.json()["status"] == "SUCCEEDED"
    assert results.json()["total"] == 8
    assert len(results.json()["items"]) == 3
    assert review.json()["total"] == 3
    assert exact.json()["total"] == 1
    sequences = [item["sequence_number"] for item in audit.json()["items"]]
    assert sequences == list(range(1, len(sequences) + 1))
    assert audit.json()["items"][-1]["event_type"] == "RUN_SUCCEEDED"
    with execution_app.state.database.session() as session:
        job = session.get(BackgroundJobRecord, uuid.UUID(executed.json()["job_id"]))
        assert job.status == "SUCCEEDED"
        assert job.progress_percentage == 100
        assert job.failure_message is None


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
async def test_run_cannot_be_queued_twice(execution_app):
    async with AsyncClient(transport=ASGITransport(app=execution_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        assert (await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")).status_code == 202
        repeated = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "EXECUTION_ALREADY_QUEUED"


@pytest.mark.anyio
async def test_future_execution_waits_until_scheduled_time(execution_app):
    now = datetime.now(UTC)
    scheduled_at = now + timedelta(hours=1)
    async with AsyncClient(
        transport=ASGITransport(app=execution_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        queued = await client.post(
            f"/api/v1/reconciliation-runs/{run_id}/execute",
            json={"scheduled_at": scheduled_at.isoformat()},
        )
        job = await client.get(f"/api/v1/background-jobs/{queued.json()['job_id']}")
        before = _worker(execution_app, clock=lambda: now).run_once()
        after = _worker(
            execution_app, clock=lambda: scheduled_at + timedelta(seconds=1)
        ).run_once()
        run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")

    assert queued.status_code == 202
    assert queued.json()["scheduled_at"] == job.json()["scheduled_at"]
    assert datetime.fromisoformat(queued.json()["scheduled_at"]) == scheduled_at
    assert before is False
    assert after is True
    assert run.json()["status"] == "SUCCEEDED"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scheduled_at", "code"),
    [
        ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), "SCHEDULE_IN_PAST"),
        ((datetime.now(UTC) + timedelta(days=366)).isoformat(), "SCHEDULE_TOO_DISTANT"),
    ],
)
async def test_invalid_execution_schedules_are_rejected(
    execution_app, scheduled_at, code
):
    async with AsyncClient(
        transport=ASGITransport(app=execution_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        response = await client.post(
            f"/api/v1/reconciliation-runs/{run_id}/execute",
            json={"scheduled_at": scheduled_at},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


@pytest.mark.anyio
async def test_naive_execution_schedule_is_rejected(execution_app):
    async with AsyncClient(
        transport=ASGITransport(app=execution_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        run_id = await _create_run(client)
        await _upload(client, run_id, "BANK_TRANSACTIONS", "bank_transactions.csv")
        await _upload(client, run_id, "ERP_INVOICES", "erp_invoices.csv")
        response = await client.post(
            f"/api/v1/reconciliation-runs/{run_id}/execute",
            json={"scheduled_at": "2030-01-01T12:00:00"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


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
        queued = await client.post(f"/api/v1/reconciliation-runs/{run_id}/execute")
        clock = [datetime.now(UTC)]
        worker = _worker(
            execution_app,
            clock=lambda: clock[0],
            retry_delay_seconds=1,
        )
        for _ in range(3):
            assert worker.run_once() is True
            clock[0] += timedelta(seconds=2)
        run = await client.get(f"/api/v1/reconciliation-runs/{run_id}")
        results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results")
        audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events")
    assert queued.status_code == 202
    assert run.json()["status"] == "FAILED"
    assert run.json()["error_message"] == "Reconciliation execution failed."
    assert results.json()["total"] == 0
    assert audit.json()["items"][-1]["event_type"] == "RUN_FAILED"
    with execution_app.state.database.session() as session:
        job = session.get(BackgroundJobRecord, uuid.UUID(queued.json()["job_id"]))
        assert job.status == "FAILED"
        assert job.failure_message == "Background job processing failed."
