"""Background-job API, authorization, and tenant-isolation coverage."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from reconcileflow.api import APISettings, create_app
from reconcileflow.api.auth_dependencies import TenantContext, get_current_user, get_tenant_context
from reconcileflow.persistence import Base, OrganizationRecord, PersistenceUnitOfWork, UserRecord


ORG_ID = uuid.UUID("70000000-0000-0000-0000-000000000001")
OTHER_ORG_ID = uuid.UUID("70000000-0000-0000-0000-000000000002")
USER_ID = uuid.UUID("70000000-0000-0000-0000-000000000003")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def jobs_app(tmp_path):
    app = create_app(APISettings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'jobs-api.db').as_posix()}",
        upload_directory=tmp_path / "uploads",
        _env_file=None,
    ))
    Base.metadata.create_all(app.state.database.engine)
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        ORG_ID, USER_ID, "OWNER"
    )
    with app.state.database.session() as session:
        session.add_all([
            UserRecord(id=USER_ID, email="jobs@example.com", password_hash="test-hash"),
            OrganizationRecord(id=ORG_ID, name="Jobs Organization", slug="jobs-organization"),
            OrganizationRecord(id=OTHER_ORG_ID, name="Other Organization", slug="other-organization"),
        ])
        session.commit()
    yield app
    app.state.database.dispose()


def _job(app, organization_id=ORG_ID):
    with app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.create(organization_id=organization_id)
            job = work.background_jobs.create(
                organization_id=organization_id, run_id=run.id
            )
            job_id = job.id
    return job_id


def _fail_job(app, job_id):
    with app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            job = work.background_jobs.get(job_id, organization_id=ORG_ID)
            work.runs.transition(job.run_id, "RUNNING", organization_id=ORG_ID)
            claimed = work.background_jobs.claim_next(
                worker_id="failure-worker", organization_id=ORG_ID
            )
            assert claimed.id == job_id
            work.runs.transition(
                job.run_id,
                "FAILED",
                organization_id=ORG_ID,
                error_code="EXECUTION_FAILED",
                error_message="Reconciliation execution failed.",
            )
            work.background_jobs.complete(
                job_id,
                "FAILED",
                organization_id=ORG_ID,
                failure_code="WORKER_PROCESSING_FAILED",
                failure_message="Background job processing failed.",
            )


@pytest.mark.anyio
async def test_list_get_filter_and_paginate_jobs_without_worker_secrets(jobs_app):
    first = _job(jobs_app)
    second = _job(jobs_app)
    _job(jobs_app, OTHER_ORG_ID)
    with jobs_app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            work.background_jobs.claim_next(
                worker_id="must-not-be-public", organization_id=ORG_ID
            )

    async with AsyncClient(
        transport=ASGITransport(app=jobs_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        listing = await client.get("/api/v1/background-jobs?limit=1&offset=0")
        running = await client.get("/api/v1/background-jobs?status=RUNNING")
        summary = await client.get("/api/v1/background-jobs/summary")
        detail = await client.get(f"/api/v1/background-jobs/{first}")

    assert listing.status_code == running.status_code == detail.status_code == 200
    assert listing.json()["total"] == 2
    assert len(listing.json()["items"]) == 1
    assert running.json()["total"] == 1
    assert summary.status_code == 200
    assert summary.json()["running"] == 1
    assert summary.json()["queued"] == 1
    assert summary.json()["queued_normal_priority"] == 1
    assert summary.json()["queued_low_priority"] == 0
    assert summary.json()["queued_high_priority"] == 0
    assert "worker_id" not in summary.text
    assert detail.json()["id"] == str(first)
    assert detail.json()["status"] == "RUNNING"
    assert set(detail.json()).isdisjoint({"claimed_by", "heartbeat_at", "storage_key"})
    assert str(second) in {item["id"] for item in (await _all_jobs(jobs_app)).json()["items"]}


async def _all_jobs(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/api/v1/background-jobs")


@pytest.mark.anyio
async def test_job_detail_does_not_disclose_another_tenant(jobs_app):
    other_job = _job(jobs_app, OTHER_ORG_ID)
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/background-jobs/{other_job}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.anyio
async def test_operator_can_cancel_queued_and_running_jobs(jobs_app):
    job_ids = {_job(jobs_app), _job(jobs_app)}
    with jobs_app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            claimed = work.background_jobs.claim_next(worker_id="worker", organization_id=ORG_ID)
            running = claimed.id
            queued = (job_ids - {running}).pop()
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        first = await client.post(f"/api/v1/background-jobs/{queued}/cancel")
        second = await client.post(f"/api/v1/background-jobs/{running}/cancel")
    statuses = {first.json()["id"]: first.json()["status"], second.json()["id"]: second.json()["status"]}
    assert set(statuses.values()) == {"CANCEL_REQUESTED", "CANCELLED"}


@pytest.mark.anyio
async def test_viewer_cannot_cancel_and_terminal_job_returns_conflict(jobs_app):
    job_id = _job(jobs_app)
    jobs_app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        ORG_ID, uuid.uuid4(), "VIEWER"
    )
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        denied = await client.post(f"/api/v1/background-jobs/{job_id}/cancel")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "INSUFFICIENT_ROLE"

    jobs_app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        ORG_ID, uuid.uuid4(), "OWNER"
    )
    with jobs_app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            claimed = work.background_jobs.claim_next(worker_id="worker", organization_id=ORG_ID)
            work.background_jobs.complete(
                claimed.id, "SUCCEEDED", organization_id=ORG_ID
            )
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        conflict = await client.post(f"/api/v1/background-jobs/{job_id}/cancel")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "JOB_NOT_CANCELLABLE"


def test_openapi_documents_job_monitoring_and_cancellation(jobs_app):
    paths = jobs_app.openapi()["paths"]
    assert "/api/v1/background-jobs" in paths
    assert "/api/v1/background-jobs/{job_id}" in paths
    operation = paths["/api/v1/background-jobs/{job_id}/cancel"]["post"]
    assert all(role in operation["description"] for role in ("OWNER", "ADMIN", "ANALYST"))


@pytest.mark.anyio
async def test_failed_job_can_be_retried_with_history_and_security_audit(jobs_app):
    job_id = _job(jobs_app)
    _fail_job(jobs_app, job_id)
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        retried = await client.post(f"/api/v1/background-jobs/{job_id}/retry")
        repeated = await client.post(f"/api/v1/background-jobs/{job_id}/retry")
        detail = await client.get(f"/api/v1/background-jobs/{job_id}")
    assert retried.status_code == 200
    assert retried.json()["id"] == str(job_id)
    assert retried.json()["status"] == "QUEUED"
    assert retried.json()["attempt_count"] == 0
    assert retried.json()["total_attempt_count"] == 1
    assert retried.json()["manual_retry_count"] == 1
    assert retried.json()["failure_code"] is None
    assert detail.json()["last_manual_retry_at"] is not None
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "JOB_NOT_RETRYABLE"
    with jobs_app.state.database.session() as session:
        work = PersistenceUnitOfWork(session)
        job = work.background_jobs.get(job_id, organization_id=ORG_ID)
        run = work.runs.get(job.run_id, organization_id=ORG_ID)
        events = work.security_audit_events.list_for_organization(ORG_ID)
    assert run.status == "PENDING"
    assert events[0].event_type == "BACKGROUND_JOB_MANUAL_RETRY_REQUESTED"
    assert set(events[0].details) == {"job_id", "run_id", "manual_retry_count"}


@pytest.mark.anyio
async def test_nonfailed_cross_tenant_and_viewer_retries_are_rejected(jobs_app):
    queued = _job(jobs_app)
    other = _job(jobs_app, OTHER_ORG_ID)
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        conflict = await client.post(f"/api/v1/background-jobs/{queued}/retry")
        hidden = await client.post(f"/api/v1/background-jobs/{other}/retry")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "JOB_NOT_RETRYABLE"
    assert hidden.status_code == 404

    with jobs_app.state.database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            work.background_jobs.request_cancellation(queued, organization_id=ORG_ID)

    failed = _job(jobs_app)
    _fail_job(jobs_app, failed)
    jobs_app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        ORG_ID, USER_ID, "VIEWER"
    )
    async with AsyncClient(transport=ASGITransport(app=jobs_app), base_url="http://test") as client:
        denied = await client.post(f"/api/v1/background-jobs/{failed}/retry")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "INSUFFICIENT_ROLE"
