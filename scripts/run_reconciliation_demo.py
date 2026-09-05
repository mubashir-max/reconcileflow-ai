"""Run the complete ReconcileFlow v0.1 workflow against synthetic fixtures."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from reconcileflow import run_reconciliation_workflow
from reconcileflow.reconciliation import ReconciliationConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = PROJECT_ROOT / "data" / "sample"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ReconcileFlow v0.1 synthetic-data demonstration.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "reconciliation-results.xlsx",
        help="Destination .csv or .xlsx report (default: output/reconciliation-results.xlsx).",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    summary = run_reconciliation_workflow(
        bank_path=SAMPLE_DIRECTORY / "bank_transactions.csv",
        erp_path=SAMPLE_DIRECTORY / "erp_invoices.csv",
        gateway_path=SAMPLE_DIRECTORY / "gateway_settlements.csv",
        output_path=arguments.output,
        reconciliation=ReconciliationConfig(amount_tolerance=Decimal("1.00")),
        overwrite=arguments.overwrite,
    )
    safe_summary = {
        "run_id": summary.audit_record.run_id,
        "status": summary.audit_record.status.value,
        "bank_transactions_loaded": summary.bank_transactions_loaded,
        "erp_invoices_loaded": summary.erp_invoices_loaded,
        "gateway_entries_loaded": summary.gateway_entries_loaded,
        "reconciliation_results": summary.reconciliation_results,
        "result_counts_by_status": dict(summary.result_counts_by_status),
        "results_requiring_review": summary.results_requiring_review,
        "output_format": summary.output_format,
        "output_filename": summary.output_path.name,
    }
    print(json.dumps(safe_summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
