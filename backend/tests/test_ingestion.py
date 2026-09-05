import csv
from datetime import timezone
from decimal import Decimal
from pathlib import Path

import pytest

from reconcileflow.ingestion import (
    IngestionConfig,
    IngestionError,
    load_bank_transactions,
    load_erp_invoices,
    load_gateway_settlements,
)


SAMPLES = Path(__file__).parents[2] / "data" / "sample"


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_loads_bank_samples(suffix):
    records = load_bank_transactions(SAMPLES / f"bank_transactions.{suffix}")
    assert len(records) == 9
    assert records[0].amount == Decimal("10500.00")
    assert records[0].ingested_at.tzinfo is not None


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_loads_invoice_samples(suffix):
    invoices = load_erp_invoices(SAMPLES / f"erp_invoices.{suffix}")
    assert len(invoices) == 8
    assert invoices[0].lines[0].line_number == 1


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_loads_gateway_samples(suffix):
    records = load_gateway_settlements(SAMPLES / f"gateway_settlements.{suffix}")
    assert len(records) == 2
    assert records[0].net_amount == Decimal("4850.00")


def test_explicit_mapping_and_unknown_columns_are_flexible(tmp_path):
    source = tmp_path / "bank.csv"
    with (SAMPLES / "bank_transactions.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader)
        values = next(reader)
    headers[headers.index("transaction_id")] = "My Bank Reference"
    headers.append("Provider Custom Flag")
    values.append("priority")
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(reversed(headers))
        writer.writerow(reversed(values))
    record = load_bank_transactions(source, IngestionConfig(column_mapping={"My Bank Reference": "transaction_id"}))[0]
    assert record.transaction_id == "TXN-20260801-001"
    assert record.extra_data["Provider Custom Flag"] == "priority"


def test_error_identifies_missing_required_column(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("transaction_id,amount\nTX-1,abc\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="missing required columns") as error:
        load_bank_transactions(source)
    assert error.value.row == 1


def test_error_identifies_invalid_value_and_source_row(tmp_path):
    source = tmp_path / "bad.csv"
    with (SAMPLES / "bank_transactions.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    rows[1][rows[0].index("amount")] = "not-money"
    with source.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows[:2])
    with pytest.raises(IngestionError) as error:
        load_bank_transactions(source)
    assert error.value.row == 2
    assert error.value.column == "amount"
    assert "not-money" in str(error.value)


def test_naive_excel_datetimes_use_configured_source_timezone():
    record = load_bank_transactions(
        SAMPLES / "bank_transactions.xlsx",
        IngestionConfig(source_timezone=timezone.utc),
    )[0]
    assert record.booking_datetime.tzinfo is timezone.utc
