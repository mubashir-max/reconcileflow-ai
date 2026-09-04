"""Generate deterministic, synthetic ReconcileFlow AI CSV fixtures.

The values are fictional. Canonical field names follow data/sample/README.md.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "sample"
ARTIFACT_INPUT = ROOT / "tmp" / "sample_data.json"

BANK_FIELDS = """source_system source_record_id transaction_id account_id statement_id entry_reference account_servicer_reference end_to_end_id instruction_id mandate_id check_number booking_date value_date authorized_date booking_datetime authorized_datetime amount currency account_currency account_amount exchange_rate credit_debit_indicator status transaction_code payment_channel category subcategory description original_description remittance_information merchant_name merchant_category_code counterparty_name counterparty_account_id counterparty_iban_masked counterparty_bic counterparty_country debtor_name creditor_name invoice_reference customer_reference bank_reference balance_after_transaction branch_id location_country location_city is_fee is_reversal reversal_of_transaction_id ingested_at extra_data_json""".split()

ERP_FIELDS = """source_system source_record_id invoice_id invoice_number invoice_type status issue_date due_date service_start_date service_end_date posting_date accounting_period currency tax_currency exchange_rate purchase_order_reference sales_order_reference contract_reference project_reference payment_reference supplier_id supplier_name supplier_tax_id supplier_country customer_id customer_name customer_tax_id customer_email customer_country billing_address_line1 billing_city billing_region billing_postal_code billing_country delivery_address_line1 delivery_city delivery_country payment_terms_code payment_terms_description payment_method payment_account_reference line_id line_number item_id item_description quantity unit_code unit_price line_discount_amount line_charge_amount line_net_amount tax_category tax_rate tax_amount line_gross_amount document_subtotal document_discount_amount document_charge_amount document_tax_amount document_total_amount prepaid_amount paid_amount amount_due last_payment_date notes created_at updated_at ingested_at extra_data_json""".split()

GATEWAY_FIELDS = """source_system source_record_id settlement_id gateway_payment_id merchant_account_id transaction_type status created_at available_on settlement_date gross_amount fee_amount tax_on_fee_amount refund_amount chargeback_amount adjustment_amount net_amount currency settlement_currency exchange_rate customer_id customer_name invoice_reference order_reference gateway_reference bank_reference payment_method_type card_brand card_last4 description ingested_at extra_data_json""".split()

EXPECTED_FIELDS = """case_id expected_status bank_source_record_ids erp_invoice_ids gateway_source_record_ids expected_amount currency tolerance_amount explanation""".split()


def record(fields: list[str], **values: object) -> dict[str, object]:
    unknown = set(values) - set(fields)
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")
    return {field: values.get(field, "") for field in fields}


COMMON_BANK = {
    "source_system": "Desert National Bank CAMT.053 Sandbox",
    "account_id": "ACCT-AED-OPERATING-001",
    "statement_id": "STMT-2026-08-001",
    "account_currency": "AED",
    "status": "BOOKED",
    "payment_channel": "bank_transfer",
    "counterparty_country": "AE",
    "creditor_name": "ReconcileFlow Demo Trading LLC",
    "branch_id": "DXB-001",
    "location_country": "AE",
    "is_fee": False,
    "is_reversal": False,
    "ingested_at": "2026-09-05T08:00:00Z",
    "extra_data_json": "{}",
}


def bank(**values: object) -> dict[str, object]:
    return record(BANK_FIELDS, **(COMMON_BANK | values))


BANK_ROWS = [
    bank(source_record_id="BANK-0001", transaction_id="TXN-20260801-001", entry_reference="NTRY-0001", account_servicer_reference="ASR-0001", end_to_end_id="E2E-INV-1001", instruction_id="INS-0001", booking_date="2026-08-01", value_date="2026-08-01", authorized_date="2026-07-31", booking_datetime="2026-08-01T09:15:00Z", authorized_datetime="2026-07-31T15:42:00Z", amount="10500.00", currency="AED", account_amount="10500.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-ESCT", category="customer_payment", subcategory="invoice_payment", description="Incoming payment from Atlas Facilities LLC", original_description="TRF ATLAS FAC INV-1001", remittance_information="Payment for INV-1001", counterparty_name="Atlas Facilities LLC", counterparty_account_id="CP-ATLAS-001", counterparty_iban_masked="AE*******************4401", counterparty_bic="DNBKAEADXXX", debtor_name="Atlas Facilities LLC", invoice_reference="INV-1001", customer_reference="CUS-ATLAS", bank_reference="BNK-REF-1001", balance_after_transaction="185500.00", location_city="Dubai"),
    bank(source_system="Euro Commerce Bank Open Banking Sandbox", source_record_id="BANK-0002", transaction_id="TXN-20260803-002", account_id="ACCT-EUR-COLLECTION-002", statement_id="STMT-2026-08-EUR", entry_reference="NTRY-0002", account_servicer_reference="ASR-0002", end_to_end_id="E2E-SET-2001", booking_date="2026-08-03", value_date="2026-08-03", authorized_date="2026-08-02", booking_datetime="2026-08-03T07:30:00Z", amount="4850.00", currency="EUR", account_currency="EUR", account_amount="4850.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-MRCH", category="gateway_payout", subcategory="card_settlement", description="Card processor payout SET-2001", original_description="PAYFLOW SET-2001 NET 4850", remittance_information="SET-2001 INV-1002", merchant_name="PayFlow Test Gateway", counterparty_name="PayFlow Europe Test Ltd", counterparty_account_id="CP-PAYFLOW-001", counterparty_iban_masked="DE******************7812", counterparty_bic="TESTDEFFXXX", counterparty_country="DE", debtor_name="PayFlow Europe Test Ltd", invoice_reference="INV-1002", customer_reference="SET-2001", bank_reference="BNK-REF-2001", balance_after_transaction="24850.00", branch_id="FRA-TEST", location_country="DE", location_city="Frankfurt"),
    bank(source_system="Northstar Bank API Sandbox", source_record_id="BANK-0003", transaction_id="TXN-20260805-003", entry_reference="NTRY-0003", account_servicer_reference="ASR-0003", end_to_end_id="E2E-INV-1003", booking_date="2026-08-05", value_date="2026-08-05", authorized_date="2026-08-05", booking_datetime="2026-08-05T11:05:00Z", amount="2400.50", currency="USD", account_currency="AED", account_amount="8814.64", exchange_rate="3.672000", credit_debit_indicator="CREDIT", transaction_code="WIRE-IN", category="customer_payment", subcategory="invoice_payment", description="USD payment with small overpayment", original_description="WIRE NOVA RETAIL INV-1003", remittance_information="INV-1003", counterparty_name="Nova Retail Group Inc", counterparty_account_id="CP-NOVA-001", counterparty_iban_masked="US******************9910", counterparty_bic="TESTUS33XXX", counterparty_country="US", debtor_name="Nova Retail Group Inc", invoice_reference="INV-1003", customer_reference="CUS-NOVA", bank_reference="BNK-REF-1003", balance_after_transaction="194314.64", branch_id="NYC-TEST", location_country="US", location_city="New York"),
    bank(source_record_id="BANK-0004", transaction_id="TXN-20260808-004", entry_reference="NTRY-0004", account_servicer_reference="ASR-0004", end_to_end_id="E2E-BATCH-1004-1005", booking_date="2026-08-08", value_date="2026-08-08", amount="3675.00", currency="AED", account_amount="3675.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-ESCT", category="customer_payment", subcategory="batch_invoice_payment", description="Combined payment for two invoices", original_description="ORBIT INV1004 INV1005", remittance_information="INV-1004 + INV-1005", counterparty_name="Orbit Hospitality FZ-LLC", counterparty_account_id="CP-ORBIT-001", counterparty_iban_masked="AE*******************2308", counterparty_bic="DNBKAEADXXX", debtor_name="Orbit Hospitality FZ-LLC", invoice_reference="INV-1004|INV-1005", customer_reference="CUS-ORBIT", bank_reference="BNK-REF-1004", balance_after_transaction="197989.64", location_city="Dubai"),
    bank(source_record_id="BANK-0005A", transaction_id="TXN-20260810-005A", entry_reference="NTRY-0005A", account_servicer_reference="ASR-0005A", booking_date="2026-08-10", value_date="2026-08-10", amount="1000.00", currency="AED", account_amount="1000.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-ESCT", category="customer_payment", subcategory="partial_payment", description="First partial payment for INV-1006", original_description="SUMMIT PART1 INV1006", remittance_information="INV-1006 PART 1", counterparty_name="Summit Technical Services LLC", counterparty_account_id="CP-SUMMIT-001", counterparty_iban_masked="AE*******************5582", counterparty_bic="DNBKAEADXXX", debtor_name="Summit Technical Services LLC", invoice_reference="INV-1006", customer_reference="CUS-SUMMIT", bank_reference="BNK-REF-1006A", balance_after_transaction="198989.64", location_city="Abu Dhabi"),
    bank(source_record_id="BANK-0005B", transaction_id="TXN-20260811-005B", entry_reference="NTRY-0005B", account_servicer_reference="ASR-0005B", booking_date="2026-08-11", value_date="2026-08-11", amount="2000.00", currency="AED", account_amount="2000.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-ESCT", category="customer_payment", subcategory="partial_payment", description="Final partial payment for INV-1006", original_description="SUMMIT PART2 INV1006", remittance_information="INV-1006 PART 2", counterparty_name="Summit Technical Services LLC", counterparty_account_id="CP-SUMMIT-001", counterparty_iban_masked="AE*******************5582", counterparty_bic="DNBKAEADXXX", debtor_name="Summit Technical Services LLC", invoice_reference="INV-1006", customer_reference="CUS-SUMMIT", bank_reference="BNK-REF-1006B", balance_after_transaction="200989.64", location_city="Abu Dhabi"),
    bank(source_record_id="BANK-0006A", transaction_id="TXN-DUP-20260812-006", entry_reference="NTRY-0006A", account_servicer_reference="ASR-0006", booking_date="2026-08-12", value_date="2026-08-12", amount="900.00", currency="AED", account_amount="900.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-ESCT", category="customer_payment", subcategory="invoice_payment", description="Payment for INV-1007", original_description="CEDAR INV1007", remittance_information="INV-1007", counterparty_name="Cedar Medical Supplies LLC", counterparty_account_id="CP-CEDAR-001", counterparty_iban_masked="AE*******************7715", counterparty_bic="DNBKAEADXXX", debtor_name="Cedar Medical Supplies LLC", invoice_reference="INV-1007", customer_reference="CUS-CEDAR", bank_reference="BNK-DUP-1007", balance_after_transaction="201889.64", location_city="Sharjah"),
    bank(source_record_id="BANK-0006B", transaction_id="TXN-DUP-20260812-006", entry_reference="NTRY-0006B", account_servicer_reference="ASR-0006", booking_date="2026-08-12", value_date="2026-08-12", amount="900.00", currency="AED", account_amount="900.00", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="PMNT-RCDT-ESCT", category="customer_payment", subcategory="invoice_payment", description="Duplicate imported payment for INV-1007", original_description="CEDAR INV1007", remittance_information="INV-1007", counterparty_name="Cedar Medical Supplies LLC", counterparty_account_id="CP-CEDAR-001", counterparty_iban_masked="AE*******************7715", counterparty_bic="DNBKAEADXXX", debtor_name="Cedar Medical Supplies LLC", invoice_reference="INV-1007", customer_reference="CUS-CEDAR", bank_reference="BNK-DUP-1007", balance_after_transaction="201889.64", location_city="Sharjah", extra_data_json='{"duplicate_import_batch":"IMPORT-002"}'),
    bank(source_record_id="BANK-0007", transaction_id="TXN-20260814-007", entry_reference="NTRY-0007", account_servicer_reference="ASR-0007", booking_date="2026-08-14", value_date="2026-08-14", amount="777.77", currency="AED", account_amount="777.77", exchange_rate="1.000000", credit_debit_indicator="CREDIT", transaction_code="CASH-DEP", payment_channel="cash", category="unclassified", subcategory="unknown_deposit", description="Unidentified cash deposit", original_description="CASH DEP BR 14", remittance_information="", counterparty_name="", counterparty_account_id="", counterparty_iban_masked="", counterparty_bic="", debtor_name="", invoice_reference="", customer_reference="", bank_reference="BNK-REF-UNKNOWN", balance_after_transaction="202667.41", location_city="Dubai", extra_data_json='{"cash_deposit_envelope":"ENV-TEST-14"}'),
]


COMMON_ERP = {
    "source_system": "Odoo Demo ERP",
    "invoice_type": "INVOICE",
    "status": "OPEN",
    "posting_date": "2026-07-01",
    "accounting_period": "2026-07",
    "supplier_id": "SUP-RECONCILEFLOW-DEMO",
    "supplier_name": "ReconcileFlow Demo Trading LLC",
    "supplier_tax_id": "AE-TRN-TEST-100000001",
    "supplier_country": "AE",
    "payment_terms_code": "NET30",
    "payment_terms_description": "Payment due within 30 days",
    "payment_method": "bank_transfer",
    "payment_account_reference": "ACCT-TOKEN-001",
    "unit_code": "EA",
    "line_discount_amount": "0.00",
    "line_charge_amount": "0.00",
    "tax_category": "STANDARD",
    "tax_rate": "5.00",
    "prepaid_amount": "0.00",
    "paid_amount": "0.00",
    "created_at": "2026-07-01T08:00:00Z",
    "updated_at": "2026-08-01T08:00:00Z",
    "ingested_at": "2026-09-05T08:05:00Z",
    "extra_data_json": "{}",
}


def invoice(**values: object) -> dict[str, object]:
    return record(ERP_FIELDS, **(COMMON_ERP | values))


def invoice_row(invoice_id: str, amount: str, customer_id: str, customer_name: str, currency: str = "AED", **values: object) -> dict[str, object]:
    numeric = float(amount)
    net = round(numeric / 1.05, 2)
    tax = round(numeric - net, 2)
    defaults = {
        "source_record_id": f"ERP-{invoice_id}-L1",
        "invoice_id": invoice_id,
        "invoice_number": invoice_id,
        "issue_date": "2026-07-01",
        "due_date": "2026-07-31",
        "service_start_date": "2026-07-01",
        "service_end_date": "2026-07-31",
        "currency": currency,
        "purchase_order_reference": f"PO-{invoice_id[4:]}",
        "sales_order_reference": f"SO-{invoice_id[4:]}",
        "contract_reference": f"CTR-{customer_id}",
        "project_reference": "PRJ-OPERATIONS-2026",
        "payment_reference": invoice_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "customer_tax_id": f"TAX-TEST-{customer_id}",
        "customer_email": f"billing+{customer_id.lower()}@example.test",
        "customer_country": "AE" if currency == "AED" else ("US" if currency == "USD" else "DE"),
        "billing_address_line1": "Synthetic Business District 1",
        "billing_city": "Dubai" if currency == "AED" else ("New York" if currency == "USD" else "Berlin"),
        "billing_region": "Dubai" if currency == "AED" else "",
        "billing_postal_code": "00000",
        "billing_country": "AE" if currency == "AED" else ("US" if currency == "USD" else "DE"),
        "delivery_address_line1": "Synthetic Delivery Zone 2",
        "delivery_city": "Dubai" if currency == "AED" else ("New York" if currency == "USD" else "Berlin"),
        "delivery_country": "AE" if currency == "AED" else ("US" if currency == "USD" else "DE"),
        "line_id": "1",
        "line_number": 1,
        "item_id": "SVC-RECON-001",
        "item_description": "Monthly reconciliation services",
        "quantity": "1.00",
        "unit_price": f"{net:.2f}",
        "line_net_amount": f"{net:.2f}",
        "tax_amount": f"{tax:.2f}",
        "line_gross_amount": f"{numeric:.2f}",
        "document_subtotal": f"{net:.2f}",
        "document_discount_amount": "0.00",
        "document_charge_amount": "0.00",
        "document_tax_amount": f"{tax:.2f}",
        "document_total_amount": f"{numeric:.2f}",
        "amount_due": f"{numeric:.2f}",
        "notes": "Synthetic fixture for reconciliation testing",
    }
    return invoice(**(defaults | values))


ERP_ROWS = [
    invoice_row("INV-1001", "10500.00", "CUS-ATLAS", "Atlas Facilities LLC", item_description="Annual facilities platform subscription"),
    invoice_row("INV-1002", "5000.00", "CUS-RHEIN", "Rhein Demo Commerce GmbH", currency="EUR", payment_method="card", item_description="Commerce integration implementation"),
    invoice_row("INV-1003", "2400.00", "CUS-NOVA", "Nova Retail Group Inc", currency="USD", item_description="Data migration and validation services"),
    invoice_row("INV-1004", "1575.00", "CUS-ORBIT", "Orbit Hospitality FZ-LLC", item_description="Property reconciliation module"),
    invoice_row("INV-1005", "2100.00", "CUS-ORBIT", "Orbit Hospitality FZ-LLC", item_description="Payment gateway connector"),
    invoice_row("INV-1006", "3000.00", "CUS-SUMMIT", "Summit Technical Services LLC", item_description="Quarterly support retainer"),
    invoice_row("INV-1007", "900.00", "CUS-CEDAR", "Cedar Medical Supplies LLC", item_description="Invoice matching configuration"),
    invoice_row("INV-1008", "1250.00", "CUS-HARBOR", "Harbor Education Services Ltd", currency="EUR", issue_date="2026-08-01", due_date="2026-08-31", posting_date="2026-08-01", accounting_period="2026-08", item_description="Policy document onboarding"),
]


COMMON_GATEWAY = {
    "source_system": "PayFlow Test Gateway",
    "merchant_account_id": "MERCHANT-DEMO-001",
    "transaction_type": "PAYMENT",
    "status": "PAID",
    "created_at": "2026-08-01T12:00:00Z",
    "available_on": "2026-08-02",
    "settlement_date": "2026-08-03",
    "tax_on_fee_amount": "0.00",
    "refund_amount": "0.00",
    "chargeback_amount": "0.00",
    "adjustment_amount": "0.00",
    "exchange_rate": "1.000000",
    "payment_method_type": "card",
    "card_brand": "visa",
    "card_last4": "4242",
    "ingested_at": "2026-09-05T08:10:00Z",
    "extra_data_json": "{}",
}


def gateway(**values: object) -> dict[str, object]:
    return record(GATEWAY_FIELDS, **(COMMON_GATEWAY | values))


GATEWAY_ROWS = [
    gateway(source_record_id="GTW-0001", settlement_id="SET-2001", gateway_payment_id="PAY-INV-1002", gross_amount="5000.00", fee_amount="150.00", net_amount="4850.00", currency="EUR", settlement_currency="EUR", customer_id="CUS-RHEIN", customer_name="Rhein Demo Commerce GmbH", invoice_reference="INV-1002", order_reference="ORD-1002", gateway_reference="ACQ-TEST-1002", bank_reference="BNK-REF-2001", description="Card payment net of processor fee"),
    gateway(source_record_id="GTW-0002", settlement_id="SET-UNPAID-2002", gateway_payment_id="PAY-INV-1008", status="AVAILABLE", created_at="2026-08-20T14:20:00Z", available_on="2026-08-22", settlement_date="2026-08-23", gross_amount="1250.00", fee_amount="37.50", net_amount="1212.50", currency="EUR", settlement_currency="EUR", customer_id="CUS-HARBOR", customer_name="Harbor Education Services Ltd", invoice_reference="INV-1008", order_reference="ORD-1008", gateway_reference="ACQ-TEST-1008", bank_reference="PENDING-SET-2002", card_brand="mastercard", card_last4="4444", description="Available gateway balance awaiting bank payout"),
]


EXPECTED_ROWS = [
    record(EXPECTED_FIELDS, case_id="CASE-001", expected_status="EXACT_MATCH", bank_source_record_ids="BANK-0001", erp_invoice_ids="INV-1001", expected_amount="10500.00", currency="AED", tolerance_amount="0.00", explanation="Invoice reference, currency, and amount match exactly."),
    record(EXPECTED_FIELDS, case_id="CASE-002", expected_status="SETTLEMENT_MATCH", bank_source_record_ids="BANK-0002", erp_invoice_ids="INV-1002", gateway_source_record_ids="GTW-0001", expected_amount="4850.00", currency="EUR", tolerance_amount="0.00", explanation="Gateway gross payment of 5000.00 less 150.00 fee equals the 4850.00 bank payout."),
    record(EXPECTED_FIELDS, case_id="CASE-003", expected_status="TOLERANCE_MATCH", bank_source_record_ids="BANK-0003", erp_invoice_ids="INV-1003", expected_amount="2400.00", currency="USD", tolerance_amount="1.00", explanation="Bank receipt exceeds the invoice by 0.50, within the configured 1.00 tolerance."),
    record(EXPECTED_FIELDS, case_id="CASE-004", expected_status="MANY_TO_ONE_MATCH", bank_source_record_ids="BANK-0004", erp_invoice_ids="INV-1004|INV-1005", expected_amount="3675.00", currency="AED", tolerance_amount="0.00", explanation="Two invoices totaling 3675.00 map to one bank receipt."),
    record(EXPECTED_FIELDS, case_id="CASE-005", expected_status="ONE_TO_MANY_MATCH", bank_source_record_ids="BANK-0005A|BANK-0005B", erp_invoice_ids="INV-1006", expected_amount="3000.00", currency="AED", tolerance_amount="0.00", explanation="Two partial bank receipts totaling 3000.00 settle one invoice."),
    record(EXPECTED_FIELDS, case_id="CASE-006", expected_status="DUPLICATE", bank_source_record_ids="BANK-0006A|BANK-0006B", erp_invoice_ids="INV-1007", expected_amount="900.00", currency="AED", tolerance_amount="0.00", explanation="Two imported entries share the same transaction ID, bank reference, date, currency, and amount."),
    record(EXPECTED_FIELDS, case_id="CASE-007", expected_status="REQUIRES_REVIEW", bank_source_record_ids="BANK-0007", expected_amount="777.77", currency="AED", tolerance_amount="0.00", explanation="Cash deposit has no invoice, customer, or gateway reference."),
    record(EXPECTED_FIELDS, case_id="CASE-008", expected_status="REQUIRES_REVIEW", erp_invoice_ids="INV-1008", gateway_source_record_ids="GTW-0002", expected_amount="1212.50", currency="EUR", tolerance_amount="0.00", explanation="Gateway balance is available, but no booked bank payout exists yet."),
]


DATASETS = {
    "bank_transactions": (BANK_FIELDS, BANK_ROWS),
    "erp_invoices": (ERP_FIELDS, ERP_ROWS),
    "gateway_settlements": (GATEWAY_FIELDS, GATEWAY_ROWS),
    "expected_reconciliation": (EXPECTED_FIELDS, EXPECTED_ROWS),
}


def write_csv(name: str, fields: list[str], rows: list[dict[str, object]]) -> None:
    path = OUTPUT_DIR / f"{name}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (fields, rows) in DATASETS.items():
        write_csv(name, fields, rows)

    ARTIFACT_INPUT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_INPUT.write_text(
        json.dumps(
            {name: {"fields": fields, "rows": rows} for name, (fields, rows) in DATASETS.items()},
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Generated " + ", ".join(f"{name}.csv ({len(rows)} rows)" for name, (_, rows) in DATASETS.items()))


if __name__ == "__main__":
    main()
