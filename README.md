# ReconcileFlow AI

ReconcileFlow AI matches bank transactions, ERP invoices, and payment-gateway settlements. Version 0.2 exposes the deterministic, explainable reconciliation core through a persistent FastAPI service backed by PostgreSQL.

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

## v0.2 capabilities

- Versioned FastAPI endpoints and generated OpenAPI documentation
- Persistent reconciliation runs, configurations, file metadata, results, and audit events
- SQLAlchemy repositories and atomic transaction boundaries
- PostgreSQL schema evolution through Alembic
- Secure, bounded CSV/XLSX uploads stored under server-generated keys
- API-driven reconciliation execution and paginated result retrieval
- Result filtering by reconciliation status and review requirement
- Docker Compose environment with health checks and durable local volumes
- Automated testing against SQLite and PostgreSQL

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
  api/                Versioned FastAPI application, schemas, and routes
  audit/              Structured events and immutable audit records
  exporting/          CSV, XLSX, and JSON-compatible result output
  ingestion/          Flexible source-file loading and normalization
  models/             Bank, invoice, gateway, and status models
  reconciliation/     Configuration, results, and deterministic rules
  persistence/        SQLAlchemy records, repositories, and transactions
  storage/            Safe local uploaded-file storage
  workflow.py         End-to-end application orchestration
backend/tests/         Automated test suite
data/sample/           Synthetic CSV/XLSX fixtures and expected outcomes
scripts/               Fixture generation and runnable v0.1 demonstration
backend/migrations/    Alembic database migrations
docs/                  Release notes and release checklists
```

Detailed fixture columns and scenarios are documented in [`data/sample/README.md`](data/sample/README.md).

## Requirements

- Python 3.12 or newer
- Git
- PowerShell commands below are written for Windows
- Docker Desktop with WSL 2 for the PostgreSQL container workflow

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

The test suite covers models, ingestion, matching, exports, workflow execution, auditing, the API, persistence, privacy protections, containers, and the demo. PostgreSQL integration tests run automatically in GitHub Actions when `RECONCILEFLOW_TEST_POSTGRESQL_URL` is configured.

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

## Versioned API

Start the local service with Docker Compose:

```powershell
docker compose up --build -d
```

Interactive API documentation is available at `http://localhost:8000/docs`. The principal v0.2 endpoints are:

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/health/live` | Confirm the API process is running. |
| `GET /api/v1/health/ready` | Confirm the API can reach its database. |
| `POST /api/v1/reconciliation-runs` | Create a pending run and configuration snapshot. |
| `GET /api/v1/reconciliation-runs` | List runs with pagination and status filtering. |
| `GET /api/v1/reconciliation-runs/{run_id}` | Retrieve one run and its status. |
| `POST /api/v1/reconciliation-runs/{run_id}/files` | Upload one bank, ERP, or gateway source file. |
| `GET /api/v1/reconciliation-runs/{run_id}/files` | List uploaded-file metadata for a run. |
| `GET /api/v1/files/{file_id}` | Retrieve one file's safe metadata. |
| `POST /api/v1/reconciliation-runs/{run_id}/execute` | Execute a pending run synchronously. |
| `GET /api/v1/reconciliation-runs/{run_id}/results` | List and filter persisted results. |
| `GET /api/v1/results/{result_id}` | Retrieve one explainable result. |
| `GET /api/v1/reconciliation-runs/{run_id}/audit-events` | Retrieve ordered audit events. |

### End-to-end API workflow

The easiest way to learn the workflow is through `/docs`: open each endpoint, select **Try it out**, and execute these steps in order:

1. Create a reconciliation run and copy its `id`.
2. Upload `data/sample/bank_transactions.csv` as `BANK_TRANSACTIONS`.
3. Upload `data/sample/erp_invoices.csv` as `ERP_INVOICES`.
4. Optionally upload `data/sample/gateway_settlements.csv` as `GATEWAY_SETTLEMENTS`.
5. Execute the run using its ID.
6. Retrieve its results and audit events.

Bank and ERP inputs are required. One file of each source type is allowed per pending run. A succeeded or failed run cannot execute again. Results support `limit`, `offset`, `status`, and `requires_review` query parameters.

### Database migrations

Containers apply migrations automatically. For a directly installed application with `RECONCILEFLOW_DATABASE_URL` configured, run:

```powershell
alembic upgrade head
alembic current
```

Create new migration revisions only when the SQLAlchemy persistence schema changes.

## Current limitations

Version 0.2 is a persistent backend foundation, not yet a deployed multi-user SaaS product. It does not include:

- Authentication, authorization, or tenant isolation
- Background job queues or asynchronous reconciliation execution
- Cloud object storage
- Web, Android, or iOS interfaces
- Human approval and override screens
- AI-assisted matching, RAG, or LangGraph orchestration
- Cross-currency reconciliation
- Provider-specific production connectors
- Large-scale matching optimization

These capabilities belong to later roadmap milestones.

## Security

Never commit credentials, `.env` files, production exports, generated reconciliation reports, or real personal and financial information. The `output/` directory is ignored because real generated reports may contain sensitive data; the synthetic source fixtures under `data/sample/` remain intentionally versioned.

## Docker and PostgreSQL development

Docker Compose runs the FastAPI service and PostgreSQL in reproducible containers. Docker Desktop must be installed and running; no Docker account or paid cloud service is required.

Create the ignored local settings file and replace both occurrences of the example password with the same local-only password:

```powershell
Copy-Item .env.docker.example .env.docker
```

Start the environment and wait for both services to become healthy:

```powershell
docker compose up --build -d
docker compose ps
```

Alembic migrations run automatically before the API starts. Open `http://localhost:8000/docs` for the interactive API documentation or check readiness with:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health/ready
```

Useful lifecycle commands:

```powershell
# Follow service logs
docker compose logs -f api

# Stop containers while preserving database and upload volumes
docker compose down

# Rebuild after dependency or Dockerfile changes
docker compose up --build -d

# Permanently remove local containers and their stored data
docker compose down --volumes
```

The final command intentionally deletes the local PostgreSQL and uploaded-file volumes. SQLite remains the default when no database URL is configured and continues to support the fast automated test suite.
