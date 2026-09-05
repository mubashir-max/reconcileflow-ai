import csv
from decimal import Decimal
from pathlib import Path

import pytest

from reconcileflow.ingestion import load_bank_transactions, load_erp_invoices, load_gateway_settlements
from reconcileflow.models import ReconciliationStatus
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationEngine


SAMPLES = Path(__file__).parents[2] / "data" / "sample"


def _sample_results(config=None):
    return ReconciliationEngine(config).reconcile(
        load_bank_transactions(SAMPLES / "bank_transactions.csv"),
        load_erp_invoices(SAMPLES / "erp_invoices.csv"),
        load_gateway_settlements(SAMPLES / "gateway_settlements.csv"),
    )


def test_samples_produce_all_documented_outcomes():
    actual = _sample_results()
    with (SAMPLES / "expected_reconciliation.csv").open(encoding="utf-8-sig", newline="") as handle:
        expected = list(csv.DictReader(handle))
    assert len(actual) == len(expected)
    def record_key(bank_ids, invoice_ids, gateway_ids):
        return (tuple(bank_ids), tuple(invoice_ids), tuple(gateway_ids))
    actual_by_records = {
        record_key(result.bank_source_record_ids, result.erp_invoice_ids, result.gateway_source_record_ids): result
        for result in actual
    }
    for row in expected:
        key = record_key(
            filter(None, row["bank_source_record_ids"].split("|")),
            filter(None, row["erp_invoice_ids"].split("|")),
            filter(None, row["gateway_source_record_ids"].split("|")),
        )
        result = actual_by_records[key]
        assert result.status.value == row["expected_status"]
        assert result.bank_source_record_ids == tuple(filter(None, row["bank_source_record_ids"].split("|")))
        assert result.erp_invoice_ids == tuple(filter(None, row["erp_invoice_ids"].split("|")))
        assert result.gateway_source_record_ids == tuple(filter(None, row["gateway_source_record_ids"].split("|")))
        assert result.currency == row["currency"]


def test_results_are_deterministic_when_inputs_are_reversed():
    banks = load_bank_transactions(SAMPLES / "bank_transactions.csv")
    invoices = load_erp_invoices(SAMPLES / "erp_invoices.csv")
    gateways = load_gateway_settlements(SAMPLES / "gateway_settlements.csv")
    engine = ReconciliationEngine()
    assert engine.reconcile(banks, invoices, gateways) == engine.reconcile(reversed(banks), reversed(invoices), reversed(gateways))


def test_zero_tolerance_leaves_near_match_for_review():
    results = _sample_results(ReconciliationConfig(amount_tolerance=Decimal("0")))
    invoice_result = next(result for result in results if result.erp_invoice_ids == ("INV-1003",))
    assert invoice_result.status is ReconciliationStatus.REQUIRES_REVIEW
    assert invoice_result.rule == "UNMATCHED_ERP_INVOICE"


def test_date_tolerance_prevents_distant_reference_match():
    results = _sample_results(ReconciliationConfig(date_tolerance_days=0))
    invoice_result = next(result for result in results if result.erp_invoice_ids == ("INV-1001",))
    assert invoice_result.status is ReconciliationStatus.REQUIRES_REVIEW


@pytest.mark.parametrize(
    "values,error",
    [
        ({"amount_tolerance": Decimal("-0.01")}, "cannot be negative"),
        ({"date_tolerance_days": -1}, "non-negative"),
        ({"maximum_group_size": 1}, "between 2 and 10"),
    ],
)
def test_invalid_configuration_is_rejected(values, error):
    with pytest.raises(ValueError, match=error):
        ReconciliationConfig(**values)


def test_no_record_is_consumed_by_conflicting_results():
    results = _sample_results()
    for attribute in ("bank_source_record_ids", "erp_invoice_ids", "gateway_source_record_ids"):
        identifiers = [identifier for result in results for identifier in getattr(result, attribute)]
        assert len(identifiers) == len(set(identifiers))


def test_currency_mismatch_is_not_matched():
    banks = load_bank_transactions(SAMPLES / "bank_transactions.csv")[:1]
    invoice = load_erp_invoices(SAMPLES / "erp_invoices.csv")[1]
    results = ReconciliationEngine().reconcile(banks, [invoice])
    assert all(result.status is ReconciliationStatus.REQUIRES_REVIEW for result in results)
