"""Immutable, safely serializable reconciliation audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


class AuditEventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    BANK_INGESTION_COMPLETED = "BANK_INGESTION_COMPLETED"
    ERP_INGESTION_COMPLETED = "ERP_INGESTION_COMPLETED"
    GATEWAY_INGESTION_COMPLETED = "GATEWAY_INGESTION_COMPLETED"
    GATEWAY_INGESTION_SKIPPED = "GATEWAY_INGESTION_SKIPPED"
    RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
    EXPORT_COMPLETED = "EXPORT_COMPLETED"
    RUN_SUCCEEDED = "RUN_SUCCEEDED"
    RUN_FAILED = "RUN_FAILED"


class AuditRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    run_id: str
    event: AuditEventType
    timestamp: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event": self.event.value,
            "timestamp": self.timestamp,
            "details": _thaw(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationAuditRecord:
    run_id: str
    status: AuditRunStatus
    started_at: str
    finished_at: str
    duration_ms: int
    bank_filename: str
    erp_filename: str
    gateway_filename: str | None
    output_filename: str
    output_format: str
    bank_transactions_loaded: int
    erp_invoices_loaded: int
    gateway_entries_loaded: int
    reconciliation_results: int
    result_counts_by_status: Mapping[str, int]
    results_requiring_review: int
    reconciliation_config: Mapping[str, str | int]
    failure_type: str | None = None
    failure_stage: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_counts_by_status", MappingProxyType(dict(sorted(self.result_counts_by_status.items()))))
        object.__setattr__(self, "reconciliation_config", MappingProxyType(dict(sorted(self.reconciliation_config.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "bank_filename": self.bank_filename,
            "erp_filename": self.erp_filename,
            "gateway_filename": self.gateway_filename,
            "output_filename": self.output_filename,
            "output_format": self.output_format,
            "bank_transactions_loaded": self.bank_transactions_loaded,
            "erp_invoices_loaded": self.erp_invoices_loaded,
            "gateway_entries_loaded": self.gateway_entries_loaded,
            "reconciliation_results": self.reconciliation_results,
            "result_counts_by_status": dict(self.result_counts_by_status),
            "results_requiring_review": self.results_requiring_review,
            "reconciliation_config": dict(self.reconciliation_config),
            "failure_type": self.failure_type,
            "failure_stage": self.failure_stage,
            "failure_message": self.failure_message,
        }
