"""End-to-end API verification against migrated PostgreSQL."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select

from reconcileflow.api import APISettings, create_app
from reconcileflow.persistence import OrganizationMembershipRecord, PersistenceUnitOfWork
from reconcileflow.worker import BackgroundWorker, ReconciliationJobProcessor


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
            "security_audit_events",
            "background_jobs",
            "workers",
        }
        assert expected_tables <= set(inspect(app.state.database.engine).get_table_names())
        assert {"timeout_seconds", "deadline_at", "priority"} <= {
            column["name"]
            for column in inspect(app.state.database.engine).get_columns("background_jobs")
        }

        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            ready = await client.get("/api/v1/health/ready")
            email = f"integration-{uuid.uuid4().hex}@example.com"
            registered = await client.post("/api/v1/auth/register", json={
                "email": email,
                "password": "correct horse battery staple",
                "organization_name": "Integration Test Organization",
            })
            failed_login = await client.post("/api/v1/auth/login", json={
                "email": email,
                "password": "incorrect password",
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
            organization_id = client.headers["X-Organization-ID"]
            organizations = await client.get("/api/v1/organizations")
            organization_profile = await client.get(f"/api/v1/organizations/{organization_id}")
            organization_updated = await client.patch(
                f"/api/v1/organizations/{organization_id}",
                json={"name": "Updated Integration Organization"},
            )
            security_audit = await client.get(
                f"/api/v1/organizations/{organization_id}/security-audit-events"
            )
            changed_password = await client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "correct horse battery staple",
                    "new_password": "updated correct horse battery staple",
                },
            )
            revoked_refresh = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
            )
            new_password_login = await client.post("/api/v1/auth/login", json={
                "email": email,
                "password": "updated correct horse battery staple",
            })
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
            scheduled_at = datetime.now(UTC) + timedelta(seconds=1)
            executed = await client.post(
                f"/api/v1/reconciliation-runs/{run_id}/execute",
                json={
                    "scheduled_at": scheduled_at.isoformat(),
                    "timeout_seconds": 120,
                    "priority": "HIGH",
                },
            )
            integration_worker = BackgroundWorker(
                session_provider=app.state.database.session,
                processor=ReconciliationJobProcessor(
                    session_provider=app.state.database.session,
                    storage=app.state.file_storage,
                ),
                worker_id="postgresql-integration-worker",
                organization_id=uuid.UUID(organization_id),
                clock=lambda: scheduled_at + timedelta(seconds=1),
            )
            assert integration_worker.run_once() is True
            worker_ready = await client.get("/api/v1/health/worker-ready")
            results = await client.get(f"/api/v1/reconciliation-runs/{run_id}/results")
            audit = await client.get(f"/api/v1/reconciliation-runs/{run_id}/audit-events")
            job_detail = await client.get(
                f"/api/v1/background-jobs/{executed.json()['job_id']}"
            )
            jobs = await client.get("/api/v1/background-jobs?status=SUCCEEDED")
            with app.state.database.session() as session:
                with PersistenceUnitOfWork(session) as work:
                    cancelled_run = work.runs.create(
                        organization_id=uuid.UUID(organization_id)
                    )
                    cancellable_job = work.background_jobs.create(
                        organization_id=uuid.UUID(organization_id),
                        run_id=cancelled_run.id,
                    )
                    cancellable_job_id = cancellable_job.id
            cancelled_job = await client.post(
                f"/api/v1/background-jobs/{cancellable_job_id}/cancel"
            )
            with app.state.database.session() as session:
                with PersistenceUnitOfWork(session) as work:
                    retry_run = work.runs.create(
                        organization_id=uuid.UUID(organization_id)
                    )
                    retry_job = work.background_jobs.create(
                        organization_id=uuid.UUID(organization_id), run_id=retry_run.id
                    )
                    work.runs.transition(
                        retry_run.id, "RUNNING", organization_id=uuid.UUID(organization_id)
                    )
                    work.background_jobs.claim_next(
                        worker_id="retry-integration-worker",
                        organization_id=uuid.UUID(organization_id),
                    )
                    work.runs.transition(
                        retry_run.id,
                        "FAILED",
                        organization_id=uuid.UUID(organization_id),
                        error_code="EXECUTION_FAILED",
                        error_message="Reconciliation execution failed.",
                    )
                    work.background_jobs.complete(
                        retry_job.id,
                        "FAILED",
                        organization_id=uuid.UUID(organization_id),
                        failure_code="WORKER_PROCESSING_FAILED",
                        failure_message="Background job processing failed.",
                    )
                    retry_job_id = retry_job.id
            retried_job = await client.post(
                f"/api/v1/background-jobs/{retry_job_id}/retry"
            )
            retry_audit = await client.get(
                f"/api/v1/organizations/{organization_id}/security-audit-events"
            )
            await client.post(f"/api/v1/background-jobs/{retry_job_id}/cancel")
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

        with app.state.database.session() as session:
            with PersistenceUnitOfWork(session) as work:
                concurrent_run = work.runs.create(organization_id=uuid.UUID(organization_id))
                concurrent_job = work.background_jobs.create(
                    organization_id=uuid.UUID(organization_id),
                    run_id=concurrent_run.id,
                )
        with (
            app.state.database.session() as first_worker_session,
            app.state.database.session() as second_worker_session,
        ):
            first_claim = PersistenceUnitOfWork(first_worker_session).background_jobs.claim_next(
                worker_id="concurrency-worker-one",
                organization_id=uuid.UUID(organization_id),
            )
            second_claim = PersistenceUnitOfWork(second_worker_session).background_jobs.claim_next(
                worker_id="concurrency-worker-two",
                organization_id=uuid.UUID(organization_id),
            )
            assert first_claim.id == concurrent_job.id
            assert second_claim is None
            first_worker_session.rollback()
            second_worker_session.rollback()

        assert ready.status_code == 200
        assert registered.status_code == 201
        assert job_detail.status_code == 200
        assert job_detail.json()["status"] == "SUCCEEDED"
        assert job_detail.json()["timeout_seconds"] == 120
        assert job_detail.json()["priority"] == "HIGH"
        assert job_detail.json()["deadline_at"] is None
        assert jobs.status_code == 200
        assert jobs.json()["total"] >= 1
        assert cancelled_job.status_code == 200
        assert cancelled_job.json()["status"] == "CANCELLED"
        assert retried_job.status_code == 200
        assert retried_job.json()["status"] == "QUEUED"
        assert retried_job.json()["total_attempt_count"] == 1
        assert any(
            item["event_type"] == "BACKGROUND_JOB_MANUAL_RETRY_REQUESTED"
            for item in retry_audit.json()["items"]
        )
        assert registered.json()["membership"]["role"] == "OWNER"
        assert failed_login.status_code == 401
        assert failed_login.json()["error"]["code"] == "INVALID_CREDENTIALS"
        assert logged_in.status_code == 200
        assert logged_in.json()["authenticated"] is True
        assert current_user.status_code == 200
        assert current_user.json()["user"]["email"] == email
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] != refresh_token
        assert logged_out.status_code == 204
        assert organizations.status_code == 200
        assert any(item["id"] == organization_id for item in organizations.json()["items"])
        assert organization_profile.status_code == 200
        assert organization_profile.json()["current_user_role"] == "OWNER"
        assert organization_updated.status_code == 200
        assert organization_updated.json()["name"] == "Updated Integration Organization"
        assert organization_updated.json()["id"] == organization_profile.json()["id"]
        assert organization_updated.json()["slug"] == organization_profile.json()["slug"]
        assert security_audit.status_code == 200
        assert {item["event_type"] for item in security_audit.json()["items"]} >= {
            "USER_REGISTERED", "LOGIN_FAILED", "USER_LOGGED_IN", "ORGANIZATION_PROFILE_UPDATED"
        }
        assert changed_password.status_code == 204
        assert revoked_refresh.status_code == 401
        assert new_password_login.status_code == 200
        assert secondary.status_code == member_added.status_code == 201
        assert member_updated.status_code == 200
        assert member_updated.json()["role"] == "ANALYST"
        assert member_removed.status_code == 204
        assert created.status_code == 201
        assert executed.status_code == 202
        assert worker_ready.status_code == 200
        assert worker_ready.json()["active_workers"] >= 1
        assert executed.json()["status"] == "QUEUED"
        assert datetime.fromisoformat(executed.json()["scheduled_at"]) == scheduled_at
        assert results.json()["total"] == 8
        assert audit.json()["items"][-1]["event_type"] == "RUN_SUCCEEDED"
        assert viewer_write.status_code == 403
        assert viewer_write.json()["error"]["code"] == "INSUFFICIENT_ROLE"
        assert viewer_read.status_code == 200
    finally:
        app.state.database.dispose()
