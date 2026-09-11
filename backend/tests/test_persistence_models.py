from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reconcileflow.persistence import AuditEventRecord, BackgroundJobRecord, Base, ConfigurationSnapshotRecord, OrganizationRecord, ReconciliationResultRecord, ReconciliationRunRecord, SourceFileRecord


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def test_metadata_defines_complete_schema() -> None:
    assert set(Base.metadata.tables) == {
        "audit_events", "configuration_snapshots", "reconciliation_results",
        "reconciliation_runs", "source_files", "organizations",
        "organization_memberships", "users", "refresh_tokens", "security_audit_events",
        "background_jobs", "background_job_events", "workers",
        "ai_match_suggestions",
    }


def test_records_and_relationships_persist(session: Session) -> None:
    organization = OrganizationRecord(name="Model Organization", slug="model-organization")
    run = ReconciliationRunRecord(organization=organization, status="RUNNING", started_at=datetime.now(UTC))
    run.source_files.append(SourceFileRecord(source_type="BANK_TRANSACTIONS", original_filename="bank.csv", content_type="text/csv", checksum_sha256="a" * 64, size_bytes=100, row_count=2))
    run.configuration = ConfigurationSnapshotRecord(amount_tolerance=Decimal("0.50"), date_tolerance_days=2, settings={"priority": "exact"})
    run.results.append(ReconciliationResultRecord(external_result_id="RESULT-1", status="EXACT_MATCH", rule="exact", bank_source_record_ids=["BANK-1"], erp_invoice_ids=["INV-1"], explanation="Reference, currency, and amount matched."))
    run.audit_events.append(AuditEventRecord(sequence_number=1, event_type="RUN_STARTED", occurred_at=datetime.now(UTC), details={"source": "api"}))
    run.background_job = BackgroundJobRecord(organization=organization, max_attempts=3)
    session.add(run)
    session.commit()

    loaded = session.get(ReconciliationRunRecord, run.id)
    assert isinstance(loaded.id, uuid.UUID)
    assert loaded.configuration.amount_tolerance == Decimal("0.5000")
    assert loaded.source_files[0].original_filename == "bank.csv"
    assert loaded.results[0].bank_source_record_ids == ["BANK-1"]
    assert loaded.audit_events[0].details == {"source": "api"}
    assert loaded.background_job.status == "QUEUED"
    assert loaded.background_job.total_attempt_count == 0
    assert loaded.background_job.manual_retry_count == 0


def test_database_constraints_reject_invalid_status(session: Session) -> None:
    organization = OrganizationRecord(name="Invalid Status Organization", slug="invalid-status-organization")
    session.add(ReconciliationRunRecord(organization=organization, status="UNKNOWN"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_database_indexes_are_created() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    indexes = {item["name"] for item in inspect(engine).get_indexes("reconciliation_results")}
    assert "ix_reconciliation_results_run_status" in indexes
    assert "ix_reconciliation_results_run_review" in indexes
    engine.dispose()
