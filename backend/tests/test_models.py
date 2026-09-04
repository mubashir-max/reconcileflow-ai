from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from reconcileflow.models import (
    BankTransaction,
    BankTransactionStatus,
    CreditDebitIndicator,
    ERPInvoice,
    GatewaySettlementEntry,
    GatewayStatus,
    GatewayTransactionType,
    InvoiceLine,
    InvoiceStatus,
    InvoiceType,
    ReconciliationStatus,
)


NOW = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)


def valid_bank(**overrides: object) -> BankTransaction:
    values: dict[str, object] = {
        "source_system": "Example Bank Sandbox",
        "source_record_id": "BANK-1",
        "transaction_id": "TXN-1",
        "account_id": "ACCOUNT-1",
        "booking_date": date(2026, 9, 1),
        "amount": Decimal("105.00"),
        "currency": "AED",
        "credit_debit_indicator": CreditDebitIndicator.CREDIT,
        "status": BankTransactionStatus.BOOKED,
        "description": "Synthetic customer payment",
        "ingested_at": NOW,
    }
    values.update(overrides)
    return BankTransaction(**values)  # type: ignore[arg-type]


def valid_line(**overrides: object) -> InvoiceLine:
    values: dict[str, object] = {
        "line_id": "LINE-1",
        "line_number": 1,
        "item_description": "Synthetic service",
        "quantity": Decimal("1"),
        "unit_price": Decimal("100.00"),
        "line_net_amount": Decimal("100.00"),
        "tax_rate": Decimal("5.00"),
        "tax_amount": Decimal("5.00"),
        "line_gross_amount": Decimal("105.00"),
    }
    values.update(overrides)
    return InvoiceLine(**values)  # type: ignore[arg-type]


def valid_invoice(**overrides: object) -> ERPInvoice:
    values: dict[str, object] = {
        "source_system": "Example ERP",
        "source_record_id": "ERP-1",
        "invoice_id": "INV-1",
        "invoice_number": "INV-1",
        "invoice_type": InvoiceType.INVOICE,
        "status": InvoiceStatus.OPEN,
        "issue_date": date(2026, 9, 1),
        "currency": "AED",
        "supplier_id": "SUP-1",
        "supplier_name": "Synthetic Supplier LLC",
        "customer_id": "CUS-1",
        "customer_name": "Synthetic Customer LLC",
        "document_subtotal": Decimal("100.00"),
        "document_discount_amount": Decimal("0.00"),
        "document_charge_amount": Decimal("0.00"),
        "document_tax_amount": Decimal("5.00"),
        "document_total_amount": Decimal("105.00"),
        "prepaid_amount": Decimal("0.00"),
        "paid_amount": Decimal("0.00"),
        "amount_due": Decimal("105.00"),
        "lines": (valid_line(),),
        "ingested_at": NOW,
    }
    values.update(overrides)
    return ERPInvoice(**values)  # type: ignore[arg-type]


def valid_gateway(**overrides: object) -> GatewaySettlementEntry:
    values: dict[str, object] = {
        "source_system": "Example Gateway",
        "source_record_id": "GTW-1",
        "settlement_id": "SET-1",
        "gateway_payment_id": "PAY-1",
        "merchant_account_id": "MERCHANT-1",
        "transaction_type": GatewayTransactionType.PAYMENT,
        "status": GatewayStatus.PAID,
        "created_at": NOW,
        "settlement_date": date(2026, 9, 3),
        "gross_amount": Decimal("100.00"),
        "fee_amount": Decimal("3.00"),
        "tax_on_fee_amount": Decimal("0.15"),
        "refund_amount": Decimal("0.00"),
        "chargeback_amount": Decimal("0.00"),
        "adjustment_amount": Decimal("0.00"),
        "net_amount": Decimal("96.85"),
        "currency": "AED",
        "settlement_currency": "AED",
        "ingested_at": NOW,
    }
    values.update(overrides)
    return GatewaySettlementEntry(**values)  # type: ignore[arg-type]


def test_valid_models_are_immutable_and_exported() -> None:
    transaction = valid_bank(extra_data={"provider_code": "TEST"})
    assert transaction.amount == Decimal("105.00")
    assert transaction.extra_data["provider_code"] == "TEST"
    assert ReconciliationStatus.EXACT_MATCH == "EXACT_MATCH"
    with pytest.raises(TypeError):
        transaction.extra_data["provider_code"] = "CHANGED"  # type: ignore[index]


@pytest.mark.parametrize("currency", ["aed", "AE", "AED1", "€UR"])
def test_invalid_currency_is_rejected(currency: str) -> None:
    with pytest.raises(ValueError, match="currency"):
        valid_bank(currency=currency)


def test_empty_identifier_is_rejected() -> None:
    with pytest.raises(ValueError, match="transaction_id"):
        valid_bank(transaction_id="  ")


def test_float_money_is_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        valid_bank(amount=105.0)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        valid_bank(ingested_at=datetime(2026, 9, 5, 8, 0))


def test_datetime_is_not_accepted_as_a_booking_date() -> None:
    with pytest.raises(TypeError, match="booking_date"):
        valid_bank(booking_date=NOW)


def test_plain_string_is_not_accepted_as_an_enum() -> None:
    with pytest.raises(TypeError, match="BankTransactionStatus"):
        valid_bank(status="BOOKED")


def test_reversal_requires_original_transaction() -> None:
    with pytest.raises(ValueError, match="reversal_of_transaction_id"):
        valid_bank(is_reversal=True)


def test_valid_invoice_totals() -> None:
    invoice = valid_invoice(extra_data={"erp_company": "DEMO"})
    assert invoice.amount_due == Decimal("105.00")
    assert invoice.lines[0].line_gross_amount == Decimal("105.00")


def test_invalid_invoice_total_is_rejected() -> None:
    with pytest.raises(ValueError, match="document_total_amount"):
        valid_invoice(document_total_amount=Decimal("106.00"), amount_due=Decimal("106.00"))


def test_invalid_invoice_line_calculation_is_rejected() -> None:
    with pytest.raises(ValueError, match="line_net_amount"):
        valid_line(line_net_amount=Decimal("99.00"), line_gross_amount=Decimal("104.00"))


def test_valid_gateway_net_calculation() -> None:
    entry = valid_gateway(extra_data={"processor_region": "AE"})
    assert entry.net_amount == Decimal("96.85")


def test_invalid_gateway_net_is_rejected() -> None:
    with pytest.raises(ValueError, match="net_amount"):
        valid_gateway(net_amount=Decimal("97.00"))


def test_cross_currency_gateway_requires_exchange_rate() -> None:
    with pytest.raises(ValueError, match="exchange_rate"):
        valid_gateway(settlement_currency="USD")
