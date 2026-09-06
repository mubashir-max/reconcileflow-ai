from __future__ import annotations

import hashlib
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import Base, PersistenceUnitOfWork, SourceFileRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def file_app(tmp_path):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'files.db').as_posix()}"
    app = create_app(APISettings(environment="test", database_url=database_url, upload_directory=tmp_path / "uploads", max_upload_size_bytes=100_000, _env_file=None))
    Base.metadata.create_all(app.state.database.engine)
    yield app
    app.state.database.dispose()


async def _create_run(client: AsyncClient) -> str:
    response = await client.post("/api/v1/reconciliation-runs", json={})
    assert response.status_code == 201
    return response.json()["id"]


async def _upload(client: AsyncClient, run_id: str, *, source_type: str = "BANK_TRANSACTIONS", filename: str = "bank.csv", content: bytes = b"id,amount\n1,10.00\n"):
    return await client.post(
        f"/api/v1/reconciliation-runs/{run_id}/files",
        data={"source_type": source_type},
        files={"file": (filename, content, "application/octet-stream")},
    )


def _xlsx() -> bytes:
    workbook = Workbook()
    workbook.active.append(["id", "amount"])
    workbook.active.append(["1", 10])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.mark.anyio
async def test_upload_csv_persists_safe_metadata_and_file(file_app):
    content = b"id,amount\n1,10.00\n"
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        response = await _upload(client, run_id, filename="../../customer bank.csv", content=content)
    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert body["run_id"] == run_id
    assert body["source_type"] == "BANK_TRANSACTIONS"
    assert body["original_filename"] == "customer bank.csv"
    assert body["content_type"] == "text/csv"
    assert body["size_bytes"] == len(content)
    assert body["checksum_sha256"] == hashlib.sha256(content).hexdigest()
    assert "storage" not in body
    stored_files = list(file_app.state.file_storage.directory.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name != "customer bank.csv"
    assert stored_files[0].read_bytes() == content


@pytest.mark.anyio
async def test_upload_valid_xlsx(file_app):
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        response = await _upload(client, run_id, source_type="ERP_INVOICES", filename="invoices.xlsx", content=_xlsx())
    assert response.status_code == 201
    assert response.json()["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.anyio
async def test_list_and_get_file_metadata(file_app):
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        first = (await _upload(client, run_id)).json()
        second = (await _upload(client, run_id, source_type="ERP_INVOICES", filename="erp.csv")).json()
        listing = await client.get(f"/api/v1/reconciliation-runs/{run_id}/files")
        retrieved = await client.get(f"/api/v1/files/{first['id']}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert [item["source_type"] for item in listing.json()["items"]] == ["BANK_TRANSACTIONS", "ERP_INVOICES"]
    assert {item["id"] for item in listing.json()["items"]} == {first["id"], second["id"]}
    assert retrieved.json() == first


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("filename", "content", "status_code", "error_code"),
    [
        ("empty.csv", b"", 422, "EMPTY_FILE"),
        ("payload.txt", b"hello", 415, "UNSUPPORTED_FILE"),
        ("fake.xlsx", b"not a workbook", 415, "UNSUPPORTED_FILE"),
        ("binary.csv", b"id\x00value", 415, "UNSUPPORTED_FILE"),
        ("late-invalid.csv", b"a" * 70_000 + b"\xff", 415, "UNSUPPORTED_FILE"),
        ("large.csv", b"a" * 100_001, 413, "FILE_TOO_LARGE"),
    ],
    ids=("empty", "unsupported-extension", "invalid-xlsx", "binary-csv", "late-invalid-utf8", "oversized"),
)
async def test_invalid_files_are_rejected_and_cleaned(file_app, filename, content, status_code, error_code):
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        response = await _upload(client, run_id, filename=filename, content=content)
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    upload_directory = file_app.state.file_storage.directory
    assert not upload_directory.exists() or list(upload_directory.iterdir()) == []


@pytest.mark.anyio
async def test_duplicate_source_type_returns_conflict_and_removes_second_file(file_app):
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        assert (await _upload(client, run_id)).status_code == 201
        response = await _upload(client, run_id, filename="replacement.csv", content=b"id\n2\n")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PERSISTENCE_CONFLICT"
    assert len(list(file_app.state.file_storage.directory.iterdir())) == 1


@pytest.mark.anyio
async def test_non_pending_run_rejects_upload(file_app):
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        with file_app.state.database.session() as session:
            with PersistenceUnitOfWork(session) as work:
                work.runs.transition(uuid.UUID(run_id), "FAILED")
        response = await _upload(client, run_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_PENDING"
    assert not file_app.state.file_storage.directory.exists()


@pytest.mark.anyio
async def test_unknown_resources_return_safe_404(file_app):
    missing_run, missing_file = uuid.uuid4(), uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        upload = await _upload(client, str(missing_run))
        listing = await client.get(f"/api/v1/reconciliation-runs/{missing_run}/files")
        metadata = await client.get(f"/api/v1/files/{missing_file}")
    assert upload.status_code == listing.status_code == metadata.status_code == 404
    assert not file_app.state.file_storage.directory.exists()


@pytest.mark.anyio
async def test_invalid_source_type_returns_422_without_writing(file_app):
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        response = await _upload(client, run_id, source_type="CUSTOMER_DATA")
    assert response.status_code == 422
    assert not file_app.state.file_storage.directory.exists()


@pytest.mark.anyio
async def test_database_failure_removes_stored_file_and_rolls_back_metadata(file_app, monkeypatch):
    def fail_add(*_args, **_kwargs):
        raise RuntimeError("database path and password must stay private")

    monkeypatch.setattr(SourceFileRepository, "add", fail_add)
    async with AsyncClient(transport=ASGITransport(app=file_app, raise_app_exceptions=False), base_url="http://test") as client:
        run_id = await _create_run(client)
        response = await _upload(client, run_id)
        listing = await client.get(f"/api/v1/reconciliation-runs/{run_id}/files")
    assert response.status_code == 500
    assert "password" not in response.text
    assert listing.json()["total"] == 0
    assert list(file_app.state.file_storage.directory.iterdir()) == []


@pytest.mark.anyio
async def test_openapi_documents_upload_and_metadata_endpoints(file_app):
    async with AsyncClient(transport=ASGITransport(app=file_app), base_url="http://test") as client:
        paths = (await client.get("/openapi.json")).json()["paths"]
    assert "post" in paths["/api/v1/reconciliation-runs/{run_id}/files"]
    assert "get" in paths["/api/v1/reconciliation-runs/{run_id}/files"]
    assert "get" in paths["/api/v1/files/{file_id}"]
