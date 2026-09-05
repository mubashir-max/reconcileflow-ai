from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, ConfigurationSnapshotRepository, PersistenceConflictError, PersistenceUnitOfWork, ReconciliationRunRecord


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def run_app(tmp_path):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'api-runs.db').as_posix()}"
    app = create_app(APISettings(environment="test", database_url=database_url, _env_file=None))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


def _payload(**overrides):
    configuration = {
        "amount_tolerance": "0.50",
        "date_tolerance_days": 3,
        "maximum_group_size": 6,
        **overrides,
    }
    return {"configuration": configuration}


@pytest.mark.anyio
async def test_create_and_retrieve_reconciliation_run(run_app):
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        created = await client.post("/api/v1/reconciliation-runs", json=_payload())
        assert created.status_code == 201
        body = created.json()
        uuid.UUID(body["id"])
        assert body["status"] == "PENDING"
        assert body["configuration"] == {
            "amount_tolerance": "0.5000",
            "date_tolerance_days": 3,
            "maximum_group_size": 6,
        }
        assert body["started_at"] is None
        assert body["finished_at"] is None
        assert body["error_code"] is None

        retrieved = await client.get(f"/api/v1/reconciliation-runs/{body['id']}")
        assert retrieved.status_code == 200
        assert retrieved.json() == body


@pytest.mark.anyio
async def test_default_configuration_is_persisted(run_app):
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/api/v1/reconciliation-runs", json={})
    assert response.status_code == 201
    assert response.json()["configuration"] == {
        "amount_tolerance": "1.0000",
        "date_tolerance_days": 14,
        "maximum_group_size": 5,
    }


@pytest.mark.anyio
async def test_list_runs_supports_pagination_and_total(run_app):
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        created_ids = {
            (await client.post("/api/v1/reconciliation-runs", json={})).json()["id"]
            for _ in range(3)
        }
        first = await client.get("/api/v1/reconciliation-runs?limit=2&offset=0")
        second = await client.get("/api/v1/reconciliation-runs?limit=2&offset=2")
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 3
    assert first.json()["limit"] == 2
    assert second.json()["offset"] == 2
    listed_ids = {item["id"] for item in first.json()["items"] + second.json()["items"]}
    assert listed_ids == created_ids


@pytest.mark.anyio
async def test_list_runs_filters_by_status(run_app):
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        failed_id = (await client.post("/api/v1/reconciliation-runs", json={})).json()["id"]
        await client.post("/api/v1/reconciliation-runs", json={})
        with run_app.state.database.session() as session:
            with PersistenceUnitOfWork(session) as work:
                work.runs.transition(uuid.UUID(failed_id), "FAILED", error_code="TEST", error_message="Safe failure.")
        response = await client.get("/api/v1/reconciliation-runs?status=FAILED")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [failed_id]


@pytest.mark.anyio
async def test_unknown_run_returns_safe_404(run_app):
    missing_id = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.get(f"/api/v1/reconciliation-runs/{missing_id}")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "RESOURCE_NOT_FOUND",
            "message": "The requested resource was not found.",
            "details": [],
        }
    }
    assert str(missing_id) not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/reconciliation-runs/not-a-uuid", None),
        ("GET", "/api/v1/reconciliation-runs?limit=0", None),
        ("GET", "/api/v1/reconciliation-runs?status=UNKNOWN", None),
        ("POST", "/api/v1/reconciliation-runs", _payload(amount_tolerance="-0.01")),
        ("POST", "/api/v1/reconciliation-runs", _payload(maximum_group_size=11)),
    ],
)
async def test_invalid_run_requests_return_422(run_app, method, path, payload):
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.request(method, path, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


@pytest.mark.anyio
async def test_creation_rolls_back_run_when_configuration_fails(run_app, monkeypatch):
    def fail_configuration(*_args, **_kwargs):
        raise RuntimeError("database detail password=secret")

    monkeypatch.setattr(ConfigurationSnapshotRepository, "add", fail_configuration)
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/api/v1/reconciliation-runs", json={})
    assert response.status_code == 500
    assert "secret" not in response.text
    with run_app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReconciliationRunRecord)) == 0


@pytest.mark.anyio
async def test_persistence_conflict_returns_safe_409(run_app, monkeypatch):
    def conflict(*_args, **_kwargs):
        raise PersistenceConflictError("unique index database_secret")

    monkeypatch.setattr(ConfigurationSnapshotRepository, "add", conflict)
    async with AsyncClient(transport=ASGITransport(app=run_app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post("/api/v1/reconciliation-runs", json={})
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "PERSISTENCE_CONFLICT",
        "message": "The request conflicts with existing data.",
        "details": [],
    }
    assert "database_secret" not in response.text


@pytest.mark.anyio
async def test_openapi_documents_run_management_endpoints(run_app):
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://test") as client:
        schema = (await client.get("/openapi.json")).json()
    assert "/api/v1/reconciliation-runs" in schema["paths"]
    assert set(schema["paths"]["/api/v1/reconciliation-runs"]) == {"get", "post"}
    assert "/api/v1/reconciliation-runs/{run_id}" in schema["paths"]
