from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from reconcileflow.persistence import Base, OrganizationRecord, PersistenceUnitOfWork, RecordNotFoundError


ORG_ID = uuid.UUID("81000000-0000-0000-0000-000000000001")
OTHER_ORG_ID = uuid.UUID("81000000-0000-0000-0000-000000000002")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        database_session.add_all([
            OrganizationRecord(id=ORG_ID, name="Events", slug="events"),
            OrganizationRecord(id=OTHER_ORG_ID, name="Other", slug="other-events"),
        ])
        database_session.commit()
        yield database_session
    engine.dispose()


def test_job_transitions_append_ordered_sanitized_events(session: Session) -> None:
    now = datetime.now(UTC)
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create(organization_id=ORG_ID)
        job = work.background_jobs.create(
            organization_id=ORG_ID, run_id=run.id, scheduled_at=now
        )
        job_id = job.id
        work.background_jobs.claim_next(worker_id="private-worker", at=now)
        work.background_jobs.update_progress(
            job_id, organization_id=ORG_ID, progress_percentage=45,
            status_message="safe status", at=now + timedelta(seconds=1),
        )
        work.background_jobs.complete(
            job_id, "SUCCEEDED", organization_id=ORG_ID,
            at=now + timedelta(seconds=2),
        )

    events = PersistenceUnitOfWork(session).background_job_events.list(
        job_id, organization_id=ORG_ID
    )
    assert [event.event_type for event in events] == [
        "JOB_QUEUED", "JOB_CLAIMED", "JOB_PROGRESS_UPDATED", "JOB_SUCCEEDED"
    ]
    assert [event.sequence_number for event in events] == [1, 2, 3, 4]
    serialized = str([event.details for event in events])
    assert "private-worker" not in serialized
    assert "status_message" not in serialized


def test_event_history_is_tenant_scoped_and_filterable(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create(organization_id=ORG_ID)
        job = work.background_jobs.create(organization_id=ORG_ID, run_id=run.id)
        job_id = job.id

    repository = PersistenceUnitOfWork(session).background_job_events
    assert repository.count(job_id, organization_id=ORG_ID, event_type="JOB_QUEUED") == 1
    with pytest.raises(RecordNotFoundError):
        repository.list(job_id, organization_id=OTHER_ORG_ID)
