"""Deterministic CSV, XLSX, and JSON-compatible result serialization."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Font

from reconcileflow.reconciliation import ReconciliationResult


RESULT_COLUMNS = (
    "result_id",
    "status",
    "rule",
    "bank_source_record_ids",
    "erp_invoice_ids",
    "gateway_source_record_ids",
    "expected_amount",
    "actual_amount",
    "amount_difference",
    "currency",
    "explanation",
    "requires_review",
)


class ResultExportError(ValueError):
    """Raised when a result export cannot be written safely."""


def _decimal_text(value: Decimal | None) -> str | None:
    """Preserve the exact decimal exponent instead of converting through float."""
    return None if value is None else format(value, "f")


def results_to_dicts(
    results: Iterable[ReconciliationResult],
) -> list[dict[str, str | bool | None]]:
    """Convert results into deterministic, directly JSON-serializable dictionaries."""
    rows: list[dict[str, str | bool | None]] = []
    for result in results:
        if not isinstance(result, ReconciliationResult):
            raise TypeError("results must contain only ReconciliationResult values")
        rows.append(
            {
                "result_id": result.result_id,
                "status": result.status.value,
                "rule": result.rule,
                "bank_source_record_ids": "|".join(result.bank_source_record_ids),
                "erp_invoice_ids": "|".join(result.erp_invoice_ids),
                "gateway_source_record_ids": "|".join(result.gateway_source_record_ids),
                "expected_amount": _decimal_text(result.expected_amount),
                "actual_amount": _decimal_text(result.actual_amount),
                "amount_difference": _decimal_text(result.amount_difference),
                "currency": result.currency,
                "explanation": result.explanation,
                "requires_review": result.requires_review,
            }
        )
    return rows


def _prepare_output(path: str | Path, expected_suffix: str, overwrite: bool) -> Path:
    output = Path(path)
    if output.suffix.casefold() != expected_suffix:
        raise ResultExportError(f"output path must use the {expected_suffix} extension: {output}")
    if output.exists():
        if output.is_dir():
            raise ResultExportError(f"output path is a directory: {output}")
        if not overwrite:
            raise FileExistsError(f"output already exists; pass overwrite=True to replace it: {output}")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ResultExportError(f"cannot create output directory {output.parent}: {exc}") from exc
    return output


def export_results_csv(
    results: Iterable[ReconciliationResult],
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write reconciliation results to a UTF-8 CSV with stable columns."""
    rows = results_to_dicts(results)
    output = _prepare_output(path, ".csv", overwrite)
    try:
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        raise ResultExportError(f"cannot write CSV output {output}: {exc}") from exc
    return output


def export_results_xlsx(
    results: Iterable[ReconciliationResult],
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write reconciliation results to an Excel workbook with stable columns."""
    rows = results_to_dicts(results)
    output = _prepare_output(path, ".xlsx", overwrite)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Reconciliation Results"
    sheet.append(RESULT_COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(tuple(row[column] for column in RESULT_COLUMNS))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    try:
        workbook.save(output)
    except OSError as exc:
        raise ResultExportError(f"cannot write XLSX output {output}: {exc}") from exc
    finally:
        workbook.close()
    return output
