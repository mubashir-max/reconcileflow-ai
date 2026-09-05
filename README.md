# ReconcileFlow AI

ReconcileFlow AI is a financial-reconciliation project for matching bank transactions, ERP invoices, and payment-gateway settlements. Version 0.1 provides a tested Python reconciliation core built around deterministic, explainable rules. Agentic AI, human-approval screens, APIs, and SaaS infrastructure are planned work and are not part of v0.1.

All repository fixtures are synthetic and anonymized. They contain no real customers, accounts, cards, or payments.

## v0.1 capabilities

- Typed, immutable financial domain models
- Flexible CSV and XLSX ingestion
- Configurable source-column mappings and common aliases
- Deterministic reconciliation with amount and date tolerances
- Explainable results with participating record IDs and applied rules
- CSV, XLSX, and JSON-compatible result serialization
- One-call end-to-end workflow
- Structured, privacy-conscious logging and immutable audit records
- Automated unit, integration, and end-to-end tests

## Architecture

```text
Bank / ERP / gateway CSV or XLSX files
                    |
                    v
        Flexible ingestion and mapping
                    |
                    v
         Typed financial domain models
                    |
                    v
       Deterministic reconciliation engine
                    |
          +---------+---------+
          |                   |
          v                   v
   CSV/XLSX exports    Structured audit trail
          |                   |
          +---------+---------+
                    v
          Reconciliation run summary
```

The layers remain independent: ingestion handles provider formats, models enforce domain invariants, reconciliation owns matching decisions, exporting creates portable reports, and the workflow coordinates them.

## Repository structure

```text
backend/src/reconcileflow/
  audit/              Structured events and immutable audit records
  exporting/          CSV, XLSX, and JSON-compatible result output
  ingestion/          Flexible source-file loading and normalization
  models/             Bank, invoice, gateway, and status models
  reconciliation/     Configuration, results, and deterministic rules
  workflow.py         End-to-end application orchestration
backend/tests/         Automated test suite
data/sample/           Synthetic CSV/XLSX fixtures and expected outcomes
scripts/               Fixture generation and runnable v0.1 demonstration
```

Detailed fixture columns and scenarios are documented in [`data/sample/README.md`](data/sample/README.md).

## Requirements

- Python 3.12 or newer
- Git
- PowerShell commands below are written for Windows

## Installation

Run every command from the repository root.

```powershell
py -m venv .venv
```

This creates an isolated Python environment in `.venv`.

```powershell
.\.venv\Scripts\Activate.ps1
```

This activates the environment. If PowerShell script execution is disabled, activation is optional; use `.\.venv\Scripts\python.exe` explicitly in the following commands.

```powershell
python -m pip install --editable ".[dev]"
```

This installs ReconcileFlow in editable mode, including test dependencies. Without activation, run:

```powershell
.\.venv\Scripts\python.exe -m pip install --editable ".[dev]"
```

## Run the tests

```powershell
python -m pytest
```

The test suite covers models, ingestion, matching, exports, workflow execution, auditing, privacy protections, and the demo.

## Run the v0.1 demonstration

```powershell
python scripts/run_reconciliation_demo.py
```

This runs the complete workflow against synthetic fixtures and creates:

```text
output/reconciliation-results.xlsx
```

Generate CSV instead:

```powershell
python scripts/run_reconciliation_demo.py --output output/reconciliation-results.csv
```

Existing files are protected. Replace an existing demo report explicitly:

```powershell
python scripts/run_reconciliation_demo.py --overwrite
```

The printed JSON summary contains safe operational counts, the run ID, status, output format, and output filename. It does not print full paths or raw financial values.

## Python workflow API

```python
from decimal import Decimal

from reconcileflow import run_reconciliation_workflow
from reconcileflow.reconciliation import ReconciliationConfig

summary = run_reconciliation_workflow(
    bank_path="data/sample/bank_transactions.csv",
    erp_path="data/sample/erp_invoices.xlsx",
    gateway_path="data/sample/gateway_settlements.csv",
    output_path="output/results.xlsx",
    reconciliation=ReconciliationConfig(
        amount_tolerance=Decimal("1.00"),
        date_tolerance_days=14,
    ),
)

print(summary.reconciliation_results)
print(summary.results_requiring_review)
```

Bank and ERP inputs are required. Gateway input is optional. CSV and XLSX formats can be mixed in the same run.

## Flexible source mapping

Real providers use different headers for the same concept. Supply an explicit mapping instead of changing ingestion code:

```python
from reconcileflow.ingestion import IngestionConfig, load_bank_transactions

transactions = load_bank_transactions(
    "provider-export.csv",
    IngestionConfig(
        column_mapping={
            "Entry Reference": "transaction_id",
            "Posted Date": "booking_date",
            "Transaction Amount": "amount",
            "Currency Code": "currency",
        }
    ),
)
```

Headers are compared case-insensitively, columns may be reordered, and unmapped provider fields are preserved in `extra_data`. Missing required columns, ambiguous mappings, and invalid values produce errors with file, row, column, and value context.

## Reconciliation rules

Rules run in a fixed priority order so identical inputs produce identical results.

| Outcome | Purpose |
| --- | --- |
| `DUPLICATE` | Quarantines repeated bank entries before they can be consumed by another match. |
| `EXACT_MATCH` | Matches invoice reference, currency, and amount exactly. |
| `SETTLEMENT_MATCH` | Connects gateway gross/fees/net, an invoice, and the resulting bank payout. |
| `TOLERANCE_MATCH` | Accepts a referenced amount difference within the configured limit. |
| `MANY_TO_ONE_MATCH` | Matches multiple referenced invoices to one bank payment. |
| `ONE_TO_MANY_MATCH` | Matches one invoice to multiple referenced bank payments. |
| `REQUIRES_REVIEW` | Preserves unmatched records and gateway payouts awaiting bank settlement. |

Records cannot be consumed by conflicting results, currencies must agree, and all monetary comparisons use `Decimal` rather than binary floating point.

## Result exports

CSV and XLSX reports use the same stable columns:

```text
result_id
status
rule
bank_source_record_ids
erp_invoice_ids
gateway_source_record_ids
expected_amount
actual_amount
amount_difference
currency
explanation
requires_review
```

Multiple participating IDs are separated with `|`. Decimal values are serialized as exact strings. Existing output files are not overwritten unless `overwrite=True` is supplied.

## Audit trail and privacy

Every workflow run receives a unique ID and emits ordered events for start, ingestion, reconciliation, export, and success or failure. The final immutable audit record includes timestamps, duration, safe filenames, configuration, counts, status, and sanitized failure information.

Audit logs intentionally exclude:

- Complete filesystem paths
- Raw source rows or arbitrary `extra_data`
- Customer and supplier names
- Account, card, payment, and transaction identifiers
- Transaction descriptions and remittance text
- Monetary values
- Raw exception messages that could contain sensitive context

Original exceptions are still re-raised to the caller for controlled application-level handling.

## Current limitations

Version 0.1 is a local Python core and demonstration—not a deployed SaaS product. It does not yet include:

- FastAPI endpoints or authentication
- PostgreSQL persistence or tenant isolation
- Background jobs and durable audit storage
- Web, Android, or iOS interfaces
- Human approval and override screens
- AI-assisted matching, RAG, or LangGraph orchestration
- Cross-currency reconciliation
- Provider-specific production connectors
- Large-scale matching optimization

These capabilities belong to later roadmap milestones.

## Security

Never commit credentials, `.env` files, production exports, generated reconciliation reports, or real personal and financial information. The `output/` directory is ignored because real generated reports may contain sensitive data; the synthetic source fixtures under `data/sample/` remain intentionally versioned.
