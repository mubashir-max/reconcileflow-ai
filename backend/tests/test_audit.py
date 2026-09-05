import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from reconcileflow import AuditTrail, run_reconciliation_workflow
from reconcileflow.audit import AuditEventType, AuditRunStatus
from reconcileflow.ingestion import IngestionError


SAMPLES = Path(__file__).parents[2] / "data" / "sample"


def _run(tmp_path, trail=None, gateway=True):
    return run_reconciliation_workflow(
        bank_path=SAMPLES / "bank_transactions.csv",
        erp_path=SAMPLES / "erp_invoices.csv",
        gateway_path=SAMPLES / "gateway_settlements.csv" if gateway else None,
        output_path=tmp_path / "reconciliation.csv",
        audit_trail=trail,
    )


def test_successful_run_has_ordered_events_and_complete_record(tmp_path):
    trail = AuditTrail()
    summary = _run(tmp_path, trail)
    assert [event.event for event in trail.events] == [
        AuditEventType.RUN_STARTED,
        AuditEventType.BANK_INGESTION_COMPLETED,
        AuditEventType.ERP_INGESTION_COMPLETED,
        AuditEventType.GATEWAY_INGESTION_COMPLETED,
        AuditEventType.RECONCILIATION_COMPLETED,
        AuditEventType.EXPORT_COMPLETED,
        AuditEventType.RUN_SUCCEEDED,
    ]
    record = summary.audit_record
    assert record is trail.record
    assert record.status is AuditRunStatus.SUCCEEDED
    assert record.bank_transactions_loaded == 9
    assert record.erp_invoices_loaded == 8
    assert record.gateway_entries_loaded == 2
    assert record.reconciliation_results == 8
    assert record.results_requiring_review == 3
    assert record.duration_ms >= 0
    assert datetime.fromisoformat(record.started_at).tzinfo is not None
    assert datetime.fromisoformat(record.finished_at).tzinfo is not None
    json.dumps(record.to_dict())


def test_gateway_skip_is_audited(tmp_path):
    trail = AuditTrail()
    _run(tmp_path, trail, gateway=False)
    assert AuditEventType.GATEWAY_INGESTION_SKIPPED in [event.event for event in trail.events]
    assert trail.record.gateway_filename is None


def test_failed_run_records_safe_failure_and_preserves_exception(tmp_path):
    trail = AuditTrail()
    secret_directory = tmp_path / "private-customer-directory"
    missing = secret_directory / "bank.csv"
    with pytest.raises(IngestionError) as caught:
        run_reconciliation_workflow(
            bank_path=missing,
            erp_path=SAMPLES / "erp_invoices.csv",
            output_path=tmp_path / "output.csv",
            audit_trail=trail,
        )
    assert caught.value.path == missing
    assert trail.record.status is AuditRunStatus.FAILED
    assert trail.record.failure_type == "IngestionError"
    assert trail.record.failure_stage == "bank_ingestion"
    assert trail.record.failure_message == "Processing failed during bank_ingestion."
    serialized = json.dumps(trail.record.to_dict())
    assert "private-customer-directory" not in serialized
    assert [event.event for event in trail.events] == [AuditEventType.RUN_STARTED, AuditEventType.RUN_FAILED]


def test_run_ids_are_unique(tmp_path):
    first = _run(tmp_path / "first").audit_record
    second = _run(tmp_path / "second").audit_record
    assert first.run_id != second.run_id


def test_structured_logs_include_run_id_without_sensitive_values(tmp_path, caplog):
    trail = AuditTrail(logging.getLogger("test.reconcileflow.audit"))
    with caplog.at_level(logging.INFO, logger="test.reconcileflow.audit"):
        summary = _run(tmp_path, trail)
    assert len(caplog.records) == len(trail.events)
    assert all(record.audit_event["run_id"] == summary.audit_record.run_id for record in caplog.records)
    text = " ".join(json.dumps(record.audit_event) for record in caplog.records)
    assert str(SAMPLES) not in text
    assert "Atlas Facilities" not in text
    assert "10500.00" not in text


def test_event_and_record_mappings_are_immutable(tmp_path):
    trail = AuditTrail()
    summary = _run(tmp_path, trail)
    with pytest.raises(TypeError):
        trail.events[0].details["changed"] = True
    reconciliation_event = next(event for event in trail.events if event.event is AuditEventType.RECONCILIATION_COMPLETED)
    with pytest.raises(TypeError):
        reconciliation_event.details["status_counts"]["CHANGED"] = 1
    with pytest.raises(TypeError):
        summary.audit_record.result_counts_by_status["CHANGED"] = 1
