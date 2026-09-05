"""End-to-end orchestration for a complete reconciliation run."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from reconcileflow.audit import AuditTrail, ReconciliationAuditRecord
from reconcileflow.exporting import export_results_csv, export_results_xlsx
from reconcileflow.ingestion import (
    IngestionConfig,
    load_bank_transactions,
    load_erp_invoices,
    load_gateway_settlements,
)
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationEngine


@dataclass(frozen=True, slots=True)
class ReconciliationRunSummary:
    """Stable operational facts returned after a successful workflow run."""

    bank_transactions_loaded: int
    erp_invoices_loaded: int
    gateway_entries_loaded: int
    reconciliation_results: int
    result_counts_by_status: Mapping[str, int]
    results_requiring_review: int
    output_format: str
    output_path: Path
    audit_record: ReconciliationAuditRecord

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result_counts_by_status",
            MappingProxyType(dict(sorted(self.result_counts_by_status.items()))),
        )


def run_reconciliation_workflow(
    *,
    bank_path: str | Path,
    erp_path: str | Path,
    output_path: str | Path,
    gateway_path: str | Path | None = None,
    bank_ingestion: IngestionConfig | None = None,
    erp_ingestion: IngestionConfig | None = None,
    gateway_ingestion: IngestionConfig | None = None,
    reconciliation: ReconciliationConfig | None = None,
    overwrite: bool = False,
    audit_trail: AuditTrail | None = None,
) -> ReconciliationRunSummary:
    """Load, reconcile, export, and summarize one financial-data run.

    Export happens only after every input has loaded and reconciliation succeeds,
    so ingestion or matching failures cannot create a misleading result report.
    """
    destination = Path(output_path)
    suffix = destination.suffix.casefold()
    output_format = {".csv": "CSV", ".xlsx": "XLSX"}.get(suffix, "UNSUPPORTED")
    reconciliation_config = reconciliation or ReconciliationConfig()
    trail = audit_trail or AuditTrail()
    trail.start(bank_path=bank_path, erp_path=erp_path, gateway_path=gateway_path, output_path=destination, output_format=output_format, config=reconciliation_config)

    try:
        if suffix not in {".csv", ".xlsx"}:
            raise ValueError("output_path must use a .csv or .xlsx extension")
        trail.begin_stage("bank_ingestion")
        banks = load_bank_transactions(bank_path, bank_ingestion)
        trail.ingestion_completed("bank", len(banks))
        trail.begin_stage("erp_ingestion")
        invoices = load_erp_invoices(erp_path, erp_ingestion)
        trail.ingestion_completed("erp", len(invoices))
        trail.begin_stage("gateway_ingestion")
        if gateway_path is not None:
            gateways = load_gateway_settlements(gateway_path, gateway_ingestion)
            trail.ingestion_completed("gateway", len(gateways))
        else:
            gateways = []
            trail.gateway_skipped()

        trail.begin_stage("reconciliation")
        results = ReconciliationEngine(reconciliation_config).reconcile(banks, invoices, gateways)
        counts = Counter(result.status.value for result in results)
        review_count = sum(result.requires_review for result in results)
        trail.reconciliation_completed(total=len(results), status_counts=dict(counts), review_count=review_count)

        trail.begin_stage("export")
        if suffix == ".csv":
            written_path = export_results_csv(results, destination, overwrite=overwrite)
        else:
            written_path = export_results_xlsx(results, destination, overwrite=overwrite)
        trail.export_completed()
        audit_record = trail.succeed()

        return ReconciliationRunSummary(
            bank_transactions_loaded=len(banks),
            erp_invoices_loaded=len(invoices),
            gateway_entries_loaded=len(gateways),
            reconciliation_results=len(results),
            result_counts_by_status=counts,
            results_requiring_review=review_count,
            output_format=output_format,
            output_path=written_path,
            audit_record=audit_record,
        )
    except Exception as error:
        trail.fail(error)
        raise
