from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from reconcileflow.maintenance import RetentionCleanup
from reconcileflow.persistence import (
    BackgroundJobRecord,
    BackgroundJobEventRecord,
    BackgroundJobStatus,
    Base,
    OrganizationRecord,
    PersistenceUnitOfWork,
    ReconciliationRunRecord,
    WorkerRecord,
)


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def _database(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cleanup.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(OrganizationRecord(name="Cleanup", slug="cleanup"))
        session.commit()
    return engine, factory


def _job(factory, status: BackgroundJobStatus, age_days: int) -> tuple[object, object]:
    with factory() as session:
        organization_id = session.scalar(select(OrganizationRecord.id))
        session.commit()
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.create(organization_id=organization_id)
            job = work.background_jobs.create(
                organization_id=organization_id, run_id=run.id, scheduled_at=NOW
            )
            run_id, job_id = run.id, job.id
        with PersistenceUnitOfWork(session):
            record = session.get(BackgroundJobRecord, job_id)
            record.status = status.value
            record.completed_at = NOW - timedelta(days=age_days) if status in {
                BackgroundJobStatus.SUCCEEDED,
                BackgroundJobStatus.FAILED,
                BackgroundJobStatus.CANCELLED,
            } else None
        return run_id, job_id


def test_dry_run_reports_without_deleting_records(tmp_path) -> None:
    engine, factory = _database(tmp_path)
    _, job_id = _job(factory, BackgroundJobStatus.SUCCEEDED, 31)
    with factory() as session:
        session.add(WorkerRecord(
            worker_id="private-worker-id", status="STOPPED",
            started_at=NOW - timedelta(days=10), heartbeat_at=NOW - timedelta(days=10),
            stopped_at=NOW - timedelta(days=10),
        ))
        session.commit()

    result = RetentionCleanup(
        session_provider=factory, succeeded_days=30, failed_days=90,
        cancelled_days=30, worker_days=7, batch_size=1, clock=lambda: NOW,
    ).run(dry_run=True)

    assert (result.eligible_jobs, result.deleted_jobs) == (1, 0)
    assert (result.eligible_workers, result.deleted_workers) == (1, 0)
    with factory() as session:
        assert session.get(BackgroundJobRecord, job_id) is not None
        assert session.get(WorkerRecord, "private-worker-id") is not None
    engine.dispose()


def test_cleanup_deletes_only_expired_operational_records_in_batches(tmp_path) -> None:
    engine, factory = _database(tmp_path)
    retained_run, expired_success = _job(factory, BackgroundJobStatus.SUCCEEDED, 31)
    _, expired_failure = _job(factory, BackgroundJobStatus.FAILED, 91)
    _, cancellation_only = _job(factory, BackgroundJobStatus.CANCELLED, 31)
    _, recent_cancelled = _job(factory, BackgroundJobStatus.CANCELLED, 5)
    _, active_job = _job(factory, BackgroundJobStatus.RUNNING, 365)
    with factory() as session:
        cancellation_record = session.get(BackgroundJobRecord, cancellation_only)
        cancellation_record.completed_at = None
        cancellation_record.cancellation_requested_at = NOW - timedelta(days=31)
        session.add_all([
            WorkerRecord(
                worker_id="old-stopped", status="STOPPED",
                started_at=NOW - timedelta(days=20), heartbeat_at=NOW - timedelta(days=20),
                stopped_at=NOW - timedelta(days=20),
            ),
            WorkerRecord(
                worker_id="stale-running", status="RUNNING",
                started_at=NOW - timedelta(days=20), heartbeat_at=NOW - timedelta(days=20),
            ),
            WorkerRecord(
                worker_id="active-running", status="RUNNING",
                started_at=NOW, heartbeat_at=NOW,
            ),
        ])
        session.commit()

    result = RetentionCleanup(
        session_provider=factory, succeeded_days=30, failed_days=90,
        cancelled_days=30, worker_days=7, batch_size=1, clock=lambda: NOW,
    ).run()

    assert (result.eligible_jobs, result.deleted_jobs) == (3, 3)
    assert (result.eligible_workers, result.deleted_workers) == (2, 2)
    with factory() as session:
        assert session.get(BackgroundJobRecord, expired_success) is None
        assert session.get(BackgroundJobRecord, expired_failure) is None
        assert session.get(BackgroundJobRecord, cancellation_only) is None
        assert session.get(BackgroundJobRecord, recent_cancelled) is not None
        assert session.get(BackgroundJobRecord, active_job) is not None
        assert session.scalar(select(func.count()).select_from(BackgroundJobEventRecord)) == 2
        assert session.get(ReconciliationRunRecord, retained_run) is not None
        assert session.scalar(select(func.count()).select_from(ReconciliationRunRecord)) == 5
        assert session.get(WorkerRecord, "old-stopped") is None
        assert session.get(WorkerRecord, "stale-running") is None
        assert session.get(WorkerRecord, "active-running") is not None
    engine.dispose()


def test_cleanup_rejects_nonpositive_configuration(tmp_path) -> None:
    _engine, factory = _database(tmp_path)
    try:
        RetentionCleanup(
            session_provider=factory, succeeded_days=0, failed_days=90,
            cancelled_days=30, worker_days=7, batch_size=100,
        )
    except ValueError as error:
        assert "positive integers" in str(error)
    else:
        raise AssertionError("invalid retention configuration was accepted")
