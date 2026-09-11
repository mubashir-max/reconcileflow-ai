from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reconcileflow.persistence import (
    BackgroundJobRecord,
    BackgroundJobPriority,
    BackgroundJobStatus,
    Base,
    InvalidStatusTransitionError,
    OrganizationRecord,
    PersistenceConflictError,
    PersistenceUnitOfWork,
    RecordNotFoundError,
)


ORGANIZATION_ID = uuid.UUID("10000000-0000-0000-0000-000000000031")
OTHER_ORGANIZATION_ID = uuid.UUID("20000000-0000-0000-0000-000000000031")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        database_session.add_all([
            OrganizationRecord(id=ORGANIZATION_ID, name="Jobs Organization", slug="jobs-organization"),
            OrganizationRecord(id=OTHER_ORGANIZATION_ID, name="Other Organization", slug="other-jobs-organization"),
        ])
        database_session.commit()
        yield database_session
    engine.dispose()


def _create_job(
    session: Session,
    *,
    organization_id: uuid.UUID = ORGANIZATION_ID,
    scheduled_at: datetime | None = None,
    max_attempts: int = 3,
    priority: BackgroundJobPriority | str = BackgroundJobPriority.NORMAL,
) -> BackgroundJobRecord:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create(organization_id=organization_id)
        return work.background_jobs.create(
            organization_id=organization_id,
            run_id=run.id,
            scheduled_at=scheduled_at,
            max_attempts=max_attempts,
            priority=priority,
        )


def test_job_creation_persists_tenant_run_and_queue_defaults(session: Session) -> None:
    job = _create_job(session)

    loaded = PersistenceUnitOfWork(session).background_jobs.get(
        job.id, organization_id=ORGANIZATION_ID
    )
    assert loaded.run_id == job.run_id
    assert loaded.status == BackgroundJobStatus.QUEUED
    assert loaded.progress_percentage == 0
    assert loaded.attempt_count == 0
    assert loaded.max_attempts == 3
    assert loaded.priority == BackgroundJobPriority.NORMAL
    assert loaded.scheduled_at is not None


def test_job_creation_rejects_wrong_tenant_and_duplicate_run(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create(organization_id=ORGANIZATION_ID)

    with pytest.raises(RecordNotFoundError):
        with PersistenceUnitOfWork(session) as work:
            work.background_jobs.create(
                organization_id=OTHER_ORGANIZATION_ID, run_id=run.id
            )

    with PersistenceUnitOfWork(session) as work:
        work.background_jobs.create(organization_id=ORGANIZATION_ID, run_id=run.id)
    with pytest.raises(PersistenceConflictError):
        with PersistenceUnitOfWork(session) as work:
            work.background_jobs.create(organization_id=ORGANIZATION_ID, run_id=run.id)


def test_tenant_scoped_get_and_list_do_not_expose_other_jobs(session: Session) -> None:
    own_job = _create_job(session)
    _create_job(session, organization_id=OTHER_ORGANIZATION_ID)
    repository = PersistenceUnitOfWork(session).background_jobs

    assert [job.id for job in repository.list(organization_id=ORGANIZATION_ID)] == [own_job.id]
    with pytest.raises(RecordNotFoundError):
        repository.get(own_job.id, organization_id=OTHER_ORGANIZATION_ID)


def test_claim_next_obeys_schedule_and_updates_attempt_state(session: Session) -> None:
    now = datetime.now(UTC)
    future_job = _create_job(session, scheduled_at=now + timedelta(hours=1))
    ready_job = _create_job(session, scheduled_at=now - timedelta(seconds=1))

    with PersistenceUnitOfWork(session) as work:
        claimed = work.background_jobs.claim_next(worker_id="test-worker", at=now)
        assert claimed.id == ready_job.id
        assert claimed.status == BackgroundJobStatus.RUNNING
        assert claimed.attempt_count == 1
        assert claimed.started_at == now
        assert claimed.claimed_by == "test-worker"

    assert PersistenceUnitOfWork(session).background_jobs.get(
        future_job.id, organization_id=ORGANIZATION_ID
    ).status == BackgroundJobStatus.QUEUED


def test_priority_claiming_is_deterministic_and_schedules_remain_authoritative(
    session: Session,
) -> None:
    now = datetime.now(UTC)
    low = _create_job(
        session, scheduled_at=now - timedelta(seconds=3), priority="LOW"
    )
    _create_job(session, scheduled_at=now - timedelta(seconds=2), priority="NORMAL")
    high = _create_job(
        session, scheduled_at=now - timedelta(seconds=1), priority="HIGH"
    )
    future_high = _create_job(
        session, scheduled_at=now + timedelta(hours=1), priority="HIGH"
    )

    with PersistenceUnitOfWork(session) as work:
        first = work.background_jobs.claim_next(
            worker_id="priority-worker", at=now, priority_aging_seconds=300
        )
    assert first.id == high.id

    with PersistenceUnitOfWork(session) as work:
        second = work.background_jobs.claim_next(
            worker_id="priority-worker", at=now, priority_aging_seconds=300
        )
    assert second.id != low.id
    assert future_high.status == BackgroundJobStatus.QUEUED


def test_priority_aging_prevents_low_priority_starvation(session: Session) -> None:
    now = datetime.now(UTC)
    aged_low = _create_job(
        session, scheduled_at=now - timedelta(seconds=601), priority="LOW"
    )
    _create_job(session, scheduled_at=now - timedelta(seconds=1), priority="HIGH")

    with PersistenceUnitOfWork(session) as work:
        claimed = work.background_jobs.claim_next(
            worker_id="aging-worker", at=now, priority_aging_seconds=300
        )

    assert claimed.id == aged_low.id


def test_invalid_job_priority_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="priority"):
        _create_job(session, priority="URGENT")


def test_progress_success_and_cancellation_lifecycle(session: Session) -> None:
    now = datetime.now(UTC)
    success_job = _create_job(session, scheduled_at=now)
    with PersistenceUnitOfWork(session) as work:
        work.background_jobs.claim_next(worker_id="test-worker", at=now)
        work.background_jobs.update_progress(
            success_job.id,
            organization_id=ORGANIZATION_ID,
            progress_percentage=40,
            status_message=" Processing input ",
        )
        completed = work.background_jobs.complete(
            success_job.id,
            BackgroundJobStatus.SUCCEEDED,
            organization_id=ORGANIZATION_ID,
            at=now + timedelta(seconds=2),
        )
        assert completed.progress_percentage == 100
        assert completed.status_message == "Processing input"

    cancelled_job = _create_job(session, scheduled_at=now)
    with PersistenceUnitOfWork(session) as work:
        work.background_jobs.claim_next(worker_id="test-worker", at=now)
        requested = work.background_jobs.request_cancellation(
            cancelled_job.id, organization_id=ORGANIZATION_ID, at=now
        )
        assert requested.status == BackgroundJobStatus.CANCEL_REQUESTED
        cancelled = work.background_jobs.complete(
            cancelled_job.id,
            BackgroundJobStatus.CANCELLED,
            organization_id=ORGANIZATION_ID,
            at=now + timedelta(seconds=1),
        )
        assert cancelled.status == BackgroundJobStatus.CANCELLED


def test_failed_job_can_be_safely_retried_until_attempt_limit(session: Session) -> None:
    now = datetime.now(UTC)
    job = _create_job(session, scheduled_at=now, max_attempts=2)
    with PersistenceUnitOfWork(session) as work:
        work.background_jobs.claim_next(worker_id="test-worker", at=now)
        retrying = work.background_jobs.complete(
            job.id,
            BackgroundJobStatus.FAILED,
            organization_id=ORGANIZATION_ID,
            failure_code="SOURCE_ERROR",
            failure_message="Input could not be processed.",
            retry_at=now + timedelta(minutes=1),
        )
        assert retrying.status == BackgroundJobStatus.QUEUED
        assert retrying.failure_message == "Input could not be processed."

    with PersistenceUnitOfWork(session) as work:
        work.background_jobs.claim_next(worker_id="test-worker", at=now + timedelta(minutes=1))
        failed = work.background_jobs.complete(
            job.id,
            BackgroundJobStatus.FAILED,
            organization_id=ORGANIZATION_ID,
            at=now + timedelta(minutes=2),
            failure_code="SOURCE_ERROR",
            failure_message="Input remained invalid.",
        )
        assert failed.status == BackgroundJobStatus.FAILED
        assert failed.attempt_count == 2


def test_invalid_progress_transitions_and_database_values_are_rejected(session: Session) -> None:
    job = _create_job(session)
    repository = PersistenceUnitOfWork(session).background_jobs
    with pytest.raises(ValueError):
        repository.update_progress(
            job.id, organization_id=ORGANIZATION_ID, progress_percentage=101
        )
    with pytest.raises(InvalidStatusTransitionError):
        repository.complete(
            job.id,
            BackgroundJobStatus.SUCCEEDED,
            organization_id=ORGANIZATION_ID,
        )

    session.add(BackgroundJobRecord(
        organization_id=ORGANIZATION_ID,
        run_id=job.run_id,
        status="UNKNOWN",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
