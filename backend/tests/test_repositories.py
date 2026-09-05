from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from reconcileflow.audit import AuditEvent, AuditEventType
from reconcileflow.models import ReconciliationStatus
from reconcileflow.persistence import (
    AuditEventRecord,
    Base,
    InvalidStatusTransitionError,
    Page,
    PersistenceConflictError,
    PersistenceUnitOfWork,
    ReconciliationRunRecord,
    RecordNotFoundError,
)
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationResult


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
    engine.dispose()


def _result(result_id: str, status: ReconciliationStatus = ReconciliationStatus.EXACT_MATCH) -> ReconciliationResult:
    return ReconciliationResult(
        result_id=result_id,
        status=status,
        rule="exact_reference_amount",
        bank_source_record_ids=(f"BANK-{result_id}",),
        erp_invoice_ids=(f"INV-{result_id}",),
        expected_amount=Decimal("100.00"),
        actual_amount=Decimal("100.00"),
        amount_difference=Decimal("0.00"),
        currency="AED",
        explanation="Reference, amount, and currency matched.",
    )


def test_unit_of_work_commits_complete_run_bundle(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
        work.source_files.add(
            run_id=run.id,
            source_type="BANK_TRANSACTIONS",
            original_filename="bank.csv",
            checksum_sha256="a" * 64,
            size_bytes=500,
            row_count=10,
        )
        work.configurations.add(run.id, ReconciliationConfig(), settings={"source": "api"})
        work.results.add_many(run.id, [_result("001"), _result("002")])
        work.audit_events.append(
            AuditEvent(
                run_id=str(run.id),
                event=AuditEventType.RUN_STARTED,
                timestamp=datetime.now(UTC).isoformat(),
                details={"request": "test"},
            )
        )

    assert session.scalar(select(func.count()).select_from(ReconciliationRunRecord)) == 1
    assert len(PersistenceUnitOfWork(session).results.list_for_run(run.id)) == 2


def test_unit_of_work_rolls_back_every_related_write(session: Session) -> None:
    with pytest.raises(RuntimeError, match="simulated failure"):
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.create()
            work.results.add_many(run.id, [_result("001")])
            raise RuntimeError("simulated failure")

    assert session.scalar(select(func.count()).select_from(ReconciliationRunRecord)) == 0


def test_run_transitions_capture_times_and_reject_terminal_changes(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
    started = datetime.now(UTC)
    with PersistenceUnitOfWork(session) as work:
        running = work.runs.transition(run.id, "RUNNING", at=started)
        assert running.started_at == started
    finished = started + timedelta(seconds=2)
    with PersistenceUnitOfWork(session) as work:
        succeeded = work.runs.transition(run.id, "SUCCEEDED", at=finished)
        assert succeeded.finished_at == finished
    with pytest.raises(InvalidStatusTransitionError):
        with PersistenceUnitOfWork(session) as work:
            work.runs.transition(run.id, "RUNNING")


def test_failed_run_stores_safe_failure_fields(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
        work.runs.transition(run.id, "FAILED", error_code="INGESTION_FAILED", error_message="Input could not be processed.")
    loaded = PersistenceUnitOfWork(session).runs.get(run.id)
    assert loaded.error_code == "INGESTION_FAILED"
    assert loaded.error_message == "Input could not be processed."


def test_repository_raises_safe_not_found_error(session: Session) -> None:
    missing_id = uuid.uuid4()
    with pytest.raises(RecordNotFoundError, match=str(missing_id)):
        PersistenceUnitOfWork(session).runs.get(missing_id)


def test_duplicate_configuration_is_a_persistence_conflict(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
        work.configurations.add(run.id, ReconciliationConfig())
    with pytest.raises(PersistenceConflictError):
        with PersistenceUnitOfWork(session) as work:
            work.configurations.add(run.id, ReconciliationConfig())


def test_run_filtering_order_and_pagination(session: Session) -> None:
    run_ids: list[uuid.UUID] = []
    for status in ("FAILED", "PENDING", "PENDING"):
        with PersistenceUnitOfWork(session) as work:
            run = work.runs.create()
            if status == "FAILED":
                work.runs.transition(run.id, "FAILED")
            run_ids.append(run.id)
    repository = PersistenceUnitOfWork(session).runs
    pending = repository.list(status="PENDING", page=Page(limit=1, offset=1))
    assert len(pending) == 1
    assert pending[0].status == "PENDING"


@pytest.mark.parametrize("page", [lambda: Page(limit=0), lambda: Page(limit=101), lambda: Page(offset=-1)])
def test_invalid_pagination_is_rejected(page) -> None:
    with pytest.raises(ValueError):
        page()


def test_result_status_filter_and_domain_translation(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
        work.results.add_many(run.id, [_result("001"), _result("002", ReconciliationStatus.REQUIRES_REVIEW)])
    review = PersistenceUnitOfWork(session).results.list_for_run(run.id, status="REQUIRES_REVIEW")
    assert [record.external_result_id for record in review] == ["002"]
    assert review[0].bank_source_record_ids == ["BANK-002"]


def test_invalid_result_status_filter_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="invalid reconciliation result status"):
        PersistenceUnitOfWork(session).results.list_for_run(uuid.uuid4(), status="NOT_A_STATUS")


def test_audit_events_receive_ordered_sequence_numbers(session: Session) -> None:
    with PersistenceUnitOfWork(session) as work:
        run = work.runs.create()
    for event_type in (AuditEventType.RUN_STARTED, AuditEventType.RUN_SUCCEEDED):
        with PersistenceUnitOfWork(session) as work:
            work.audit_events.append(AuditEvent(run_id=str(run.id), event=event_type, timestamp=datetime.now(UTC).isoformat()))
    events = PersistenceUnitOfWork(session).audit_events.list_for_run(run.id)
    assert [event.sequence_number for event in events] == [1, 2]
    assert [event.event_type for event in events] == ["RUN_STARTED", "RUN_SUCCEEDED"]


def test_unit_of_work_translates_database_integrity_errors(session: Session) -> None:
    duplicate_id = uuid.uuid4()
    with PersistenceUnitOfWork(session) as work:
        work.runs.create(run_id=duplicate_id)
    with pytest.raises(PersistenceConflictError, match="conflicting persistence data"):
        with PersistenceUnitOfWork(session) as work:
            work.runs.create(run_id=duplicate_id)
