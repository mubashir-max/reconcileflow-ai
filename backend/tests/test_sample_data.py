from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "sample"


def load(name: str) -> list[dict[str, str]]:
    with (SAMPLE_DIR / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_expected_sample_files_exist() -> None:
    for stem in (
        "bank_transactions",
        "erp_invoices",
        "gateway_settlements",
        "expected_reconciliation",
    ):
        assert (SAMPLE_DIR / f"{stem}.csv").is_file()
        assert (SAMPLE_DIR / f"{stem}.xlsx").is_file()


def test_bank_required_fields_and_formats() -> None:
    rows = load("bank_transactions.csv")
    assert rows
    required = {
        "source_system",
        "source_record_id",
        "transaction_id",
        "account_id",
        "booking_date",
        "amount",
        "currency",
        "credit_debit_indicator",
        "status",
        "description",
        "is_fee",
        "is_reversal",
        "ingested_at",
    }
    assert required <= rows[0].keys()
    for row in rows:
        assert all(row[field] for field in required)
        date.fromisoformat(row["booking_date"])
        datetime.fromisoformat(row["ingested_at"].replace("Z", "+00:00"))
        assert Decimal(row["amount"]) > 0
        assert len(row["currency"]) == 3 and row["currency"].isupper()
        assert row["credit_debit_indicator"] in {"CREDIT", "DEBIT"}
        json.loads(row["extra_data_json"])


def test_erp_totals_and_identifiers() -> None:
    rows = load("erp_invoices.csv")
    assert rows
    keys = [(row["source_system"], row["invoice_id"], row["line_id"]) for row in rows]
    assert len(keys) == len(set(keys))
    for row in rows:
        date.fromisoformat(row["issue_date"])
        assert Decimal(row["amount_due"]) == (
            Decimal(row["document_total_amount"])
            - Decimal(row["prepaid_amount"])
            - Decimal(row["paid_amount"])
        )
        assert Decimal(row["line_gross_amount"]) == Decimal(row["line_net_amount"]) + Decimal(row["tax_amount"])
        json.loads(row["extra_data_json"])


def test_gateway_net_amounts() -> None:
    rows = load("gateway_settlements.csv")
    for row in rows:
        expected_net = (
            Decimal(row["gross_amount"])
            - Decimal(row["fee_amount"])
            - Decimal(row["tax_on_fee_amount"])
            - Decimal(row["refund_amount"])
            - Decimal(row["chargeback_amount"])
            + Decimal(row["adjustment_amount"])
        )
        assert Decimal(row["net_amount"]) == expected_net


def test_all_reconciliation_scenarios_are_covered() -> None:
    rows = load("expected_reconciliation.csv")
    statuses = {row["expected_status"] for row in rows}
    assert statuses == {
        "EXACT_MATCH",
        "SETTLEMENT_MATCH",
        "TOLERANCE_MATCH",
        "MANY_TO_ONE_MATCH",
        "ONE_TO_MANY_MATCH",
        "DUPLICATE",
        "REQUIRES_REVIEW",
    }
