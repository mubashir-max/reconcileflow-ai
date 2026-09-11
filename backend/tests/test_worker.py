from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from reconcileflow.api import APISettings
from reconcileflow.persistence import (
    BackgroundJobStatus,
    Base,
    Database,
    OrganizationRecord,
    PersistenceUnitOfWork,
)
from reconcileflow.worker import BackgroundWorker


@pytest.fixture
def worker_database(tmp_path):
    settings = APISettings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'worker.db').as_posix()}",
        _env_file=None,
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    yield database
    database.dispose()


def _queued_job(database: Database, *, max_attempts: int = 3):
    suffix = uuid.uuid4().hex
    with database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            organization = work.organizations.create(
                name=f"Worker Organization {suffix}",
                slug=f"worker-{suffix}",
            )
            run = work.runs.create(organization_id=organization.id)
            return work.background_jobs.create(
                organization_id=organization.id,
                run_id=run.id,
                max_attempts=max_attempts,
            )


def _load(database: Database, job):
    with database.session() as session:
        return PersistenceUnitOfWork(session).background_jobs.get(
            job.id, organization_id=job.organization_id
        )


def test_worker_claims_reports_progress_and_completes_job(worker_database: Database):
    job = _queued_job(worker_database)

    def process(claimed, context):
        assert claimed.id == job.id
        context.checkpoint(
            claimed, progress_percentage=50, status_message="Processing reconciliation"
        )

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=process,
        worker_id="worker-success",
    )

    assert worker.run_once() is True
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.SUCCEEDED
    assert loaded.progress_percentage == 100
    assert loaded.status_message == "Processing reconciliation"
    assert loaded.claimed_by is None
    assert loaded.heartbeat_at is None
    with worker_database.session() as session:
        active, stale = PersistenceUnitOfWork(session).workers.health_counts(
            stale_before=datetime.now(UTC) - timedelta(minutes=1)
        )
    assert (active, stale) == (1, 0)


def test_worker_failure_is_sanitized_and_scheduled_for_retry(worker_database: Database):
    job = _queued_job(worker_database)

    def fail(_job, _context):
        raise RuntimeError("password=do-not-persist")

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=fail,
        worker_id="worker-failure",
        retry_delay_seconds=10,
    )

    assert worker.run_once() is True
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.QUEUED
    assert loaded.failure_code == "WORKER_PROCESSING_FAILED"
    assert loaded.failure_message == "Background job processing failed."
    assert "do-not-persist" not in loaded.failure_message
    assert loaded.retry_at is not None


def test_worker_timeout_is_sanitized_and_retries_safely(worker_database: Database):
    job = _queued_job(worker_database, max_attempts=2)
    clock = [datetime.now(UTC)]

    def exceed_deadline(claimed, context):
        assert claimed.deadline_at == clock[0] + timedelta(seconds=900)
        clock[0] = claimed.deadline_at
        context.checkpoint(claimed, progress_percentage=25)

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=exceed_deadline,
        worker_id="worker-timeout",
        retry_delay_seconds=10,
        clock=lambda: clock[0],
    )

    assert worker.run_once() is True
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.QUEUED
    assert loaded.failure_code == "JOB_TIMEOUT"
    assert loaded.failure_message == "Background job exceeded its execution timeout."
    assert loaded.deadline_at is None
    assert loaded.retry_at.replace(tzinfo=UTC) == clock[0] + timedelta(seconds=10)


def test_exhausted_timeout_fails_terminally(worker_database: Database):
    job = _queued_job(worker_database, max_attempts=1)
    clock = [datetime.now(UTC)]

    def exceed_deadline(claimed, context):
        clock[0] = claimed.deadline_at
        context.checkpoint(claimed, progress_percentage=25)

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=exceed_deadline,
        worker_id="worker-timeout-final",
        clock=lambda: clock[0],
    )

    assert worker.run_once() is True
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.FAILED
    assert loaded.completed_at.replace(tzinfo=UTC) == clock[0]
    assert loaded.deadline_at is None


def test_worker_checkpoint_detects_and_completes_cancellation(worker_database: Database):
    job = _queued_job(worker_database)
    clock = [datetime.now(UTC)]

    def process(claimed, context):
        with worker_database.session() as session:
            with PersistenceUnitOfWork(session) as work:
                work.background_jobs.request_cancellation(
                    claimed.id, organization_id=claimed.organization_id
                )
        clock[0] = claimed.deadline_at + timedelta(seconds=1)
        context.checkpoint(claimed, progress_percentage=25)

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=process,
        worker_id="worker-cancel",
        clock=lambda: clock[0],
    )

    assert worker.run_once() is True
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.CANCELLED
    assert loaded.failure_code is None


def test_worker_recovers_stale_lease_before_processing(worker_database: Database):
    job = _queued_job(worker_database)
    now = datetime.now(UTC)
    with worker_database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            claimed = work.background_jobs.claim_next(worker_id="interrupted-worker", at=now)
            claimed.started_at = now - timedelta(minutes=10)
            claimed.heartbeat_at = now - timedelta(minutes=10)

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=lambda _job, _context: None,
        worker_id="replacement-worker",
        stale_timeout_seconds=60,
        clock=lambda: now,
    )

    assert worker.run_once() is True
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.SUCCEEDED
    assert loaded.attempt_count == 2


def test_exhausted_stale_job_fails_without_processing(worker_database: Database):
    job = _queued_job(worker_database, max_attempts=1)
    now = datetime.now(UTC)
    with worker_database.session() as session:
        with PersistenceUnitOfWork(session) as work:
            claimed = work.background_jobs.claim_next(worker_id="interrupted-worker", at=now)
            claimed.started_at = now - timedelta(minutes=10)
            claimed.heartbeat_at = now - timedelta(minutes=10)

    processed = []
    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=lambda claimed, _context: processed.append(claimed.id),
        worker_id="replacement-worker",
        stale_timeout_seconds=60,
        clock=lambda: now,
    )

    assert worker.run_once() is False
    loaded = _load(worker_database, job)
    assert loaded.status == BackgroundJobStatus.FAILED
    assert loaded.failure_message == "Background processing was interrupted."
    assert processed == []


def test_worker_loop_stops_gracefully_after_current_job(worker_database: Database):
    _queued_job(worker_database)
    stop_event = threading.Event()

    def process(_job, _context):
        stop_event.set()

    worker = BackgroundWorker(
        session_provider=worker_database.session,
        processor=process,
        worker_id="worker-shutdown",
        poll_interval_seconds=0.1,
    )
    worker.run_forever(stop_event)

    assert stop_event.is_set()
    with worker_database.session() as session:
        active, stale = PersistenceUnitOfWork(session).workers.health_counts(
            stale_before=datetime.now(UTC) - timedelta(minutes=1)
        )
    assert (active, stale) == (0, 0)
