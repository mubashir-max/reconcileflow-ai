# Sample financial data schema

This directory contains synthetic, anonymized source-system exports used to develop and test ReconcileFlow AI. No record may contain real customer, employee, bank-account, card, or payment data.

## Design principles

- CSV headers use stable `snake_case` canonical names.
- Dates use ISO 8601 (`YYYY-MM-DD`) and timestamps include a timezone (`YYYY-MM-DDTHH:MM:SSZ`).
- Monetary values are decimal strings with `.` as the decimal separator and no currency symbol or thousands separator.
- Currency values use ISO 4217 three-letter codes such as `AED`, `USD`, and `EUR`.
- Identifiers, account numbers, references, and postal codes are strings, even when they contain only digits.
- Required fields form a small portable core; source-specific fields remain optional.
- Missing optional values are empty cells, not invented placeholders such as `N/A`.
- Every record includes `source_system`, `source_record_id`, and `ingested_at` for lineage and idempotency.
- `extra_data_json` can preserve source-specific properties that do not yet have canonical columns.

## Flexible source-column mapping

Real exports use different labels for the same concept. Importers must map source headers to canonical fields through configuration rather than embedding one bank or ERP's column names in Python logic.

Example aliases:

| Canonical field | Possible source headers |
| --- | --- |
| `transaction_id` | `Transaction ID`, `Entry Reference`, `Bank Reference`, `NtryRef` |
| `booking_date` | `Booking Date`, `Posted Date`, `Date`, `BookgDt` |
| `value_date` | `Value Date`, `Effective Date`, `ValDt` |
| `amount` | `Amount`, `Transaction Amount`, `Amt` |
| `currency` | `Currency`, `Currency Code`, `Ccy` |
| `invoice_number` | `Invoice No`, `Document Number`, `DocNum`, `ID` |
| `customer_id` | `Customer ID`, `Account Code`, `Business Partner`, `Debtor ID` |

The ingestion layer will eventually receive a mapping such as:

```yaml
source: example_bank
record_type: bank_transaction
columns:
  Entry Reference: transaction_id
  Posted Date: booking_date
  Transaction Amount: amount
  Currency Code: currency
  Remittance Information: remittance_information
```

Rules for flexible mapping:

1. Normalize source headers by trimming whitespace and comparing case-insensitively.
2. Resolve explicit source mappings before built-in aliases.
3. Validate that all canonical required fields are present after mapping.
4. Preserve unknown columns in `extra_data_json` instead of silently discarding them.
5. Reject ambiguous mappings when two source columns target the same canonical field.
6. Keep original source values available for audit and troubleshooting.

## `bank_transactions.csv`

One row represents one booked or pending entry on a bank account. The schema draws on ISO 20022 bank-to-customer statements (CAMT.053) and common Open Banking transaction objects.

| Column | Type | Required | Description |
| --- | --- | --- | --- |
| `source_system` | string | yes | Originating bank, file format, or provider identifier. |
| `source_record_id` | string | yes | Stable identifier in the source system. |
| `transaction_id` | string | yes | Canonical transaction identifier; unique except for intentional duplicate tests. |
| `account_id` | string | yes | Internal or tokenized account identifier. Never use a real account number. |
| `statement_id` | string | no | Statement or import-batch identifier. |
| `entry_reference` | string | no | Bank statement entry reference. |
| `account_servicer_reference` | string | no | Reference assigned by the account-servicing bank. |
| `end_to_end_id` | string | no | Payment end-to-end identifier. |
| `instruction_id` | string | no | Payment instruction identifier. |
| `mandate_id` | string | no | Direct-debit mandate identifier. |
| `check_number` | string | no | Cheque/check number when applicable. |
| `booking_date` | date | yes | Date the transaction was posted to the account. |
| `value_date` | date | no | Date funds become effective for interest/value purposes. |
| `authorized_date` | date | no | Date the payer authorized or initiated the transaction. |
| `booking_datetime` | datetime | no | Precise posting timestamp when supplied. |
| `authorized_datetime` | datetime | no | Precise authorization timestamp when supplied. |
| `amount` | decimal | yes | Non-negative transaction amount. Direction is represented separately. |
| `currency` | string | yes | ISO 4217 transaction currency. |
| `account_currency` | string | no | ISO 4217 currency of the bank account. |
| `account_amount` | decimal | no | Amount converted into the account currency. |
| `exchange_rate` | decimal | no | Applied currency-conversion rate. |
| `credit_debit_indicator` | enum | yes | `CREDIT` for incoming funds or `DEBIT` for outgoing funds. |
| `status` | enum | yes | `BOOKED`, `PENDING`, `REVERSED`, or `CANCELLED`. |
| `transaction_code` | string | no | Bank/provider transaction type or ISO bank transaction code. |
| `payment_channel` | string | no | Channel such as `bank_transfer`, `card`, `cash`, `cheque`, or `direct_debit`. |
| `category` | string | no | High-level normalized category. |
| `subcategory` | string | no | More specific normalized category. |
| `description` | string | yes | Human-readable transaction description. |
| `original_description` | string | no | Unmodified description supplied by the bank. |
| `remittance_information` | string | no | Payment narrative or remittance text used for matching. |
| `merchant_name` | string | no | Enriched merchant name, when relevant. |
| `merchant_category_code` | string | no | Four-character merchant category code, stored as text. |
| `counterparty_name` | string | no | Payer or payee name. |
| `counterparty_account_id` | string | no | Tokenized counterparty account identifier. |
| `counterparty_iban_masked` | string | no | Masked IBAN only; never store a real full IBAN in sample data. |
| `counterparty_bic` | string | no | Synthetic BIC/SWIFT identifier. |
| `counterparty_country` | string | no | ISO 3166-1 alpha-2 country code. |
| `debtor_name` | string | no | Originating debtor name for transfers. |
| `creditor_name` | string | no | Receiving creditor name for transfers. |
| `invoice_reference` | string | no | Invoice reference parsed or supplied by the bank. |
| `customer_reference` | string | no | Customer-facing payment reference. |
| `bank_reference` | string | no | Additional bank reference. |
| `balance_after_transaction` | decimal | no | Account balance immediately after booking. |
| `branch_id` | string | no | Synthetic branch or routing identifier. |
| `location_country` | string | no | ISO country for card/merchant location. |
| `location_city` | string | no | City for card/merchant location. |
| `is_fee` | boolean | yes | Whether this entry is a bank or processing fee. |
| `is_reversal` | boolean | yes | Whether this entry reverses an earlier entry. |
| `reversal_of_transaction_id` | string | no | Original transaction ID when `is_reversal` is true. |
| `ingested_at` | datetime | yes | Time the record entered ReconcileFlow AI. |
| `extra_data_json` | JSON string | no | Valid JSON object containing unmapped source-specific fields. |

### Bank validation rules

- The combination of `source_system`, `account_id`, and `source_record_id` must be unique except in intentional duplicate fixtures.
- `amount` must be greater than zero; use `credit_debit_indicator` instead of a signed amount.
- `reversal_of_transaction_id` is required when `is_reversal` is true.
- `account_amount` and `exchange_rate` are expected when `account_currency` differs from `currency`.
- Pending entries may lack bank references that become available only after booking.

## `erp_invoices.csv`

One row represents one invoice line. Invoice header values repeat across rows sharing the same `invoice_id`; this supports taxes, discounts, products, and partial reconciliation without requiring nested data in CSV. The schema is informed by OASIS Universal Business Language (UBL) invoice structures.

| Column | Type | Required | Description |
| --- | --- | --- | --- |
| `source_system` | string | yes | Originating ERP or accounting system. |
| `source_record_id` | string | yes | Stable source-system record ID for this invoice line. |
| `invoice_id` | string | yes | Canonical invoice identifier. |
| `invoice_number` | string | yes | Human-facing invoice or document number. |
| `invoice_type` | enum | yes | `INVOICE`, `CREDIT_NOTE`, `DEBIT_NOTE`, or `PROFORMA`. |
| `status` | enum | yes | `DRAFT`, `OPEN`, `PARTIALLY_PAID`, `PAID`, `VOID`, or `OVERDUE`. |
| `issue_date` | date | yes | Invoice issue date. |
| `due_date` | date | no | Contractual payment due date. |
| `service_start_date` | date | no | Start of the billed service period. |
| `service_end_date` | date | no | End of the billed service period. |
| `posting_date` | date | no | ERP/general-ledger posting date. |
| `accounting_period` | string | no | Accounting period such as `2026-09`. |
| `currency` | string | yes | ISO 4217 invoice currency. |
| `tax_currency` | string | no | ISO currency used for tax reporting. |
| `exchange_rate` | decimal | no | Rate used to convert into the ledger/base currency. |
| `purchase_order_reference` | string | no | Customer purchase-order number. |
| `sales_order_reference` | string | no | Seller sales-order number. |
| `contract_reference` | string | no | Related contract identifier. |
| `project_reference` | string | no | Related project, job, or cost object. |
| `payment_reference` | string | no | Reference the customer should include with payment. |
| `supplier_id` | string | yes | Supplier/legal-entity identifier. |
| `supplier_name` | string | yes | Supplier legal or trading name. |
| `supplier_tax_id` | string | no | Synthetic tax registration identifier. |
| `supplier_country` | string | no | ISO 3166-1 alpha-2 country code. |
| `customer_id` | string | yes | Customer/account identifier. |
| `customer_name` | string | yes | Customer legal or trading name. |
| `customer_tax_id` | string | no | Synthetic customer tax identifier. |
| `customer_email` | string | no | Synthetic billing email. |
| `customer_country` | string | no | ISO 3166-1 alpha-2 country code. |
| `billing_address_line1` | string | no | Synthetic billing street/address line. |
| `billing_city` | string | no | Billing city. |
| `billing_region` | string | no | State, province, or emirate. |
| `billing_postal_code` | string | no | Postal code stored as text. |
| `billing_country` | string | no | ISO 3166-1 alpha-2 country code. |
| `delivery_address_line1` | string | no | Synthetic delivery address line. |
| `delivery_city` | string | no | Delivery city. |
| `delivery_country` | string | no | ISO 3166-1 alpha-2 country code. |
| `payment_terms_code` | string | no | Terms code such as `NET30`. |
| `payment_terms_description` | string | no | Human-readable payment terms. |
| `payment_method` | string | no | Expected method such as `bank_transfer` or `card`. |
| `payment_account_reference` | string | no | Tokenized settlement account reference. |
| `line_id` | string | yes | Invoice-line identifier unique within the invoice. |
| `line_number` | integer | yes | Display/order number for the invoice line. |
| `item_id` | string | no | Product, service, SKU, or ERP item identifier. |
| `item_description` | string | yes | Description of goods or services. |
| `quantity` | decimal | yes | Invoiced quantity. |
| `unit_code` | string | no | Unit-of-measure code such as `EA` or `HUR`. |
| `unit_price` | decimal | yes | Price per unit before line discounts and tax. |
| `line_discount_amount` | decimal | yes | Discount allocated to this line; use `0.00` when absent. |
| `line_charge_amount` | decimal | yes | Additional charge allocated to this line. |
| `line_net_amount` | decimal | yes | Net amount for the line before tax. |
| `tax_category` | string | no | Tax category or exemption code. |
| `tax_rate` | decimal | yes | Percentage rate represented as `5.00`, not `0.05`. |
| `tax_amount` | decimal | yes | Tax amount for this line. |
| `line_gross_amount` | decimal | yes | Line net amount plus tax. |
| `document_subtotal` | decimal | yes | Invoice-wide line-extension/subtotal amount. |
| `document_discount_amount` | decimal | yes | Invoice-wide allowances/discounts. |
| `document_charge_amount` | decimal | yes | Invoice-wide charges. |
| `document_tax_amount` | decimal | yes | Total invoice tax. |
| `document_total_amount` | decimal | yes | Invoice total including tax and charges. |
| `prepaid_amount` | decimal | yes | Amount paid before the current balance calculation. |
| `paid_amount` | decimal | yes | Total payments applied in the ERP. |
| `amount_due` | decimal | yes | Outstanding amount expected from the customer. |
| `last_payment_date` | date | no | Date of the most recently applied payment. |
| `notes` | string | no | Non-sensitive invoice notes. |
| `created_at` | datetime | no | Source record creation time. |
| `updated_at` | datetime | no | Source record update time. |
| `ingested_at` | datetime | yes | Time the record entered ReconcileFlow AI. |
| `extra_data_json` | JSON string | no | Valid JSON object containing unmapped ERP-specific fields. |

### ERP invoice validation rules

- `(source_system, invoice_id, line_id)` must be unique except in intentional duplicate fixtures.
- Header values repeated for the same `invoice_id` must remain identical across all its line rows.
- `quantity`, `unit_price`, rates, and monetary totals use decimal arithmetic, never binary floating-point arithmetic.
- `line_net_amount = quantity * unit_price - line_discount_amount + line_charge_amount`, subject to the documented rounding policy.
- `amount_due = document_total_amount - prepaid_amount - paid_amount` for ordinary invoices.
- Credit notes retain non-negative monetary fields and use `invoice_type` to represent their accounting direction.

## `gateway_settlements.csv`

One row represents a gateway balance transaction contributing to a payout or settlement. Multiple rows may share a `settlement_id`.

| Column | Type | Required | Description |
| --- | --- | --- | --- |
| `source_system` | string | yes | Gateway or processor identifier. |
| `source_record_id` | string | yes | Stable source-system record ID. |
| `settlement_id` | string | yes | Settlement or payout grouping identifier. |
| `gateway_payment_id` | string | yes | Gateway payment/charge identifier. |
| `merchant_account_id` | string | yes | Synthetic gateway merchant-account identifier. |
| `transaction_type` | enum | yes | `PAYMENT`, `REFUND`, `CHARGEBACK`, `FEE`, `ADJUSTMENT`, or `RESERVE`. |
| `status` | enum | yes | `PENDING`, `AVAILABLE`, `PAID`, `FAILED`, or `REVERSED`. |
| `created_at` | datetime | yes | Gateway transaction creation timestamp. |
| `available_on` | date | no | Date funds became available for payout. |
| `settlement_date` | date | yes | Payout or settlement date. |
| `gross_amount` | decimal | yes | Gross transaction amount. |
| `fee_amount` | decimal | yes | Processing fee amount. |
| `tax_on_fee_amount` | decimal | yes | Tax charged on the processing fee. |
| `refund_amount` | decimal | yes | Refunded portion. |
| `chargeback_amount` | decimal | yes | Disputed/charged-back portion. |
| `adjustment_amount` | decimal | yes | Other signed settlement adjustment. |
| `net_amount` | decimal | yes | Amount contributed to the payout. |
| `currency` | string | yes | ISO 4217 transaction currency. |
| `settlement_currency` | string | yes | ISO 4217 payout currency. |
| `exchange_rate` | decimal | no | Gateway conversion rate, when applicable. |
| `customer_id` | string | no | Synthetic gateway customer identifier. |
| `customer_name` | string | no | Synthetic customer name. |
| `invoice_reference` | string | no | ERP invoice reference in gateway metadata. |
| `order_reference` | string | no | Merchant order reference. |
| `gateway_reference` | string | no | Processor/acquirer reference. |
| `bank_reference` | string | no | Reference expected on the bank payout. |
| `payment_method_type` | string | no | Method such as `card`, `wallet`, or `bank_transfer`. |
| `card_brand` | string | no | Card brand when applicable. |
| `card_last4` | string | no | Synthetic last four digits only. |
| `description` | string | no | Human-readable settlement description. |
| `ingested_at` | datetime | yes | Time the record entered ReconcileFlow AI. |
| `extra_data_json` | JSON string | no | Valid JSON object containing unmapped gateway fields. |

### Gateway validation rules

- `(source_system, source_record_id)` must be unique except in intentional duplicate fixtures.
- The settlement net calculation and sign convention must be documented and tested.
- A `settlement_id` may contain many payments, refunds, fees, and adjustments.
- Cross-currency rows require `exchange_rate` and `settlement_currency`.

## Reconciliation scenario map

The generated samples will include a separate `expected_reconciliation.csv` fixture with one row per expected result. It will identify the participating source record IDs and one of these expected outcomes:

- `EXACT_MATCH`
- `SETTLEMENT_MATCH`
- `TOLERANCE_MATCH`
- `MANY_TO_ONE_MATCH`
- `ONE_TO_MANY_MATCH`
- `DUPLICATE`
- `REQUIRES_REVIEW`

Keeping expected outcomes separate from raw source exports prevents test-only answers from leaking into production-shaped input data.

## Source references

- [ISO 20022 Bank-to-Customer Cash Management message definitions](https://www.iso20022.org/iso-20022-message-definitions?search=Bank-to-Customer+Cash+Management)
- [Plaid Transactions API reference](https://plaid.com/docs/api/products/transactions/)
- [OASIS UBL 2.4 Invoice specification](https://docs.oasis-open.org/ubl/os-UBL-2.4/mod/summary/reports/UBL-Invoice-2.4.html)

