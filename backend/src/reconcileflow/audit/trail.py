"""Structured logging collector for one reconciliation run."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic_ns
from typing import Any
from uuid import uuid4

from reconcileflow.reconciliation import ReconciliationConfig

from .events import AuditEvent, AuditEventType, AuditRunStatus, ReconciliationAuditRecord


class AuditTrail:
    """Collect ordered events and emit them through standard structured logging."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.run_id = str(uuid4())
        self._logger = logger or logging.getLogger("reconcileflow.audit")
        self._events: list[AuditEvent] = []
        self._record: ReconciliationAuditRecord | None = None
        self._started_at: datetime | None = None
        self._started_ns: int | None = None
        self._metadata: dict[str, Any] = {}
        self._counts = {"bank": 0, "erp": 0, "gateway": 0, "results": 0, "review": 0}
        self._status_counts: dict[str, int] = {}
        self._stage = "initialization"

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    @property
    def record(self) -> ReconciliationAuditRecord | None:
        return self._record

    def start(
        self,
        *,
        bank_path: str | Path,
        erp_path: str | Path,
        gateway_path: str | Path | None,
        output_path: str | Path,
        output_format: str,
        config: ReconciliationConfig,
    ) -> None:
        if self._started_at is not None:
            raise RuntimeError("audit trail has already started")
        self._started_at = datetime.now(timezone.utc)
        self._started_ns = monotonic_ns()
        self._metadata = {
            "bank_filename": Path(bank_path).name,
            "erp_filename": Path(erp_path).name,
            "gateway_filename": Path(gateway_path).name if gateway_path is not None else None,
            "output_filename": Path(output_path).name,
            "output_format": output_format,
            "reconciliation_config": {
                "amount_tolerance": format(config.amount_tolerance, "f"),
                "date_tolerance_days": config.date_tolerance_days,
                "maximum_group_size": config.maximum_group_size,
            },
        }
        self.emit(AuditEventType.RUN_STARTED)

    def emit(self, event_type: AuditEventType, **details: Any) -> None:
        event = AuditEvent(
            run_id=self.run_id,
            event=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details=details,
        )
        self._events.append(event)
        self._logger.info("reconciliation_audit", extra={"audit_event": event.to_dict()})

    def begin_stage(self, stage: str) -> None:
        """Identify the active safe processing stage for failure auditing."""
        self._stage = stage

    def ingestion_completed(self, source: str, count: int) -> None:
        event_types = {
            "bank": AuditEventType.BANK_INGESTION_COMPLETED,
            "erp": AuditEventType.ERP_INGESTION_COMPLETED,
            "gateway": AuditEventType.GATEWAY_INGESTION_COMPLETED,
        }
        self._counts[source] = count
        self.emit(event_types[source], records_loaded=count)

    def gateway_skipped(self) -> None:
        self.emit(AuditEventType.GATEWAY_INGESTION_SKIPPED)

    def reconciliation_completed(self, *, total: int, status_counts: dict[str, int], review_count: int) -> None:
        self._counts["results"] = total
        self._counts["review"] = review_count
        self._status_counts = dict(status_counts)
        self.emit(AuditEventType.RECONCILIATION_COMPLETED, results=total, results_requiring_review=review_count, status_counts=dict(sorted(status_counts.items())))

    def export_completed(self) -> None:
        self.emit(AuditEventType.EXPORT_COMPLETED, output_format=self._metadata["output_format"], output_filename=self._metadata["output_filename"])

    def succeed(self) -> ReconciliationAuditRecord:
        self.emit(AuditEventType.RUN_SUCCEEDED)
        self._record = self._finish(AuditRunStatus.SUCCEEDED)
        return self._record

    def fail(self, error: BaseException) -> ReconciliationAuditRecord:
        # Only type and stage are retained; exception text can contain paths or source values.
        safe_message = f"Processing failed during {self._stage}."
        self.emit(AuditEventType.RUN_FAILED, failure_type=type(error).__name__, failure_stage=self._stage, failure_message=safe_message)
        self._record = self._finish(AuditRunStatus.FAILED, type(error).__name__, self._stage, safe_message)
        return self._record

    def _finish(self, status: AuditRunStatus, failure_type: str | None = None, failure_stage: str | None = None, failure_message: str | None = None) -> ReconciliationAuditRecord:
        if self._started_at is None or self._started_ns is None:
            raise RuntimeError("audit trail has not started")
        finished = datetime.now(timezone.utc)
        return ReconciliationAuditRecord(
            run_id=self.run_id,
            status=status,
            started_at=self._started_at.isoformat(),
            finished_at=finished.isoformat(),
            duration_ms=max(0, (monotonic_ns() - self._started_ns) // 1_000_000),
            bank_filename=self._metadata["bank_filename"],
            erp_filename=self._metadata["erp_filename"],
            gateway_filename=self._metadata["gateway_filename"],
            output_filename=self._metadata["output_filename"],
            output_format=self._metadata["output_format"],
            bank_transactions_loaded=self._counts["bank"],
            erp_invoices_loaded=self._counts["erp"],
            gateway_entries_loaded=self._counts["gateway"],
            reconciliation_results=self._counts["results"],
            result_counts_by_status=self._status_counts,
            results_requiring_review=self._counts["review"],
            reconciliation_config=self._metadata["reconciliation_config"],
            failure_type=failure_type,
            failure_stage=failure_stage,
            failure_message=failure_message,
        )
