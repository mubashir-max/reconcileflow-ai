"""Background processor for durable reconciliation jobs."""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack

from reconcileflow.audit import AuditEventType, AuditTrail
from reconcileflow.ingestion import (
    load_bank_transactions,
    load_erp_invoices,
    load_gateway_settlements,
)
from reconcileflow.persistence import PersistenceUnitOfWork
from reconcileflow.reconciliation import ReconciliationConfig, ReconciliationEngine
from reconcileflow.storage import FileStorage

from .service import JobCancelled, JobTimedOut, SessionProvider, WorkerContext, WorkerJob


class ReconciliationJobProcessor:
    """Execute one tenant-scoped run without exposing storage or source details."""

    def __init__(
        self,
        *,
        session_provider: SessionProvider,
        storage: FileStorage,
    ) -> None:
        self._session_provider = session_provider
        self._storage = storage

    def __call__(self, job: WorkerJob, context: WorkerContext) -> None:
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                run = work.runs.get(
                    job.run_id, organization_id=job.organization_id, lock=True
                )
                if run.status == "SUCCEEDED":
                    return
                if run.status == "PENDING":
                    work.runs.transition(
                        job.run_id, "RUNNING", organization_id=job.organization_id
                    )
                elif run.status != "RUNNING":
                    raise RuntimeError("reconciliation run cannot be processed")
                files = {
                    item.source_type: item
                    for item in work.source_files.list_for_run(job.run_id)
                }
                config_record = work.configurations.get_for_run(job.run_id)

        config = ReconciliationConfig(
            amount_tolerance=config_record.amount_tolerance,
            date_tolerance_days=config_record.date_tolerance_days,
            maximum_group_size=int(config_record.settings["maximum_group_size"]),
        )
        trail = AuditTrail()
        trail.run_id = str(job.run_id)
        materializations = ExitStack()
        try:
            paths = {
                source_type: materializations.enter_context(
                    self._storage.materialize(record.storage_key or "")
                )
                for source_type, record in files.items()
            }
            trail.start(
                bank_path=paths["BANK_TRANSACTIONS"],
                erp_path=paths["ERP_INVOICES"],
                gateway_path=paths.get("GATEWAY_SETTLEMENTS"),
                output_path="database",
                output_format="DATABASE",
                config=config,
            )
            context.checkpoint(job, progress_percentage=10, status_message="Loading bank transactions")
            trail.begin_stage("bank_ingestion")
            banks = load_bank_transactions(paths["BANK_TRANSACTIONS"])
            trail.ingestion_completed("bank", len(banks))

            context.checkpoint(job, progress_percentage=35, status_message="Loading ERP invoices")
            trail.begin_stage("erp_ingestion")
            invoices = load_erp_invoices(paths["ERP_INVOICES"])
            trail.ingestion_completed("erp", len(invoices))

            context.checkpoint(job, progress_percentage=60, status_message="Loading gateway settlements")
            trail.begin_stage("gateway_ingestion")
            if "GATEWAY_SETTLEMENTS" in paths:
                gateways = load_gateway_settlements(paths["GATEWAY_SETTLEMENTS"])
                trail.ingestion_completed("gateway", len(gateways))
            else:
                gateways = []
                trail.gateway_skipped()

            context.checkpoint(job, progress_percentage=75, status_message="Reconciling records")
            trail.begin_stage("reconciliation")
            results = ReconciliationEngine(config).reconcile(banks, invoices, gateways)
            counts = Counter(item.status.value for item in results)
            review_count = sum(item.requires_review for item in results)
            trail.reconciliation_completed(
                total=len(results),
                status_counts=dict(counts),
                review_count=review_count,
            )
            context.checkpoint(job, progress_percentage=95, status_message="Saving results")
            trail.succeed()

            context.checkpoint(job, progress_percentage=99, status_message="Finalizing results")

            with self._session_provider() as session:
                with PersistenceUnitOfWork(session) as work:
                    current = work.runs.get(
                        job.run_id, organization_id=job.organization_id, lock=True
                    )
                    if current.status == "SUCCEEDED":
                        return
                    if current.status != "RUNNING":
                        raise RuntimeError("reconciliation run cannot be completed")
                    work.results.add_many(job.run_id, results)
                    for event in trail.events:
                        work.audit_events.append(event)
                    work.runs.transition(
                        job.run_id, "SUCCEEDED", organization_id=job.organization_id
                    )
        except JobCancelled as error:
            self._fail_run(job, trail, error, code="EXECUTION_CANCELLED")
            raise
        except JobTimedOut as error:
            if job.attempt_count >= job.max_attempts:
                self._fail_run(job, trail, error, code="EXECUTION_TIMEOUT")
            raise
        except Exception as error:
            if job.attempt_count >= job.max_attempts:
                self._fail_run(job, trail, error, code="EXECUTION_FAILED")
            raise
        finally:
            materializations.close()

    def _fail_run(
        self,
        job: WorkerJob,
        trail: AuditTrail,
        error: BaseException,
        *,
        code: str,
    ) -> None:
        if trail.events:
            trail.fail(error)
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                current = work.runs.get(
                    job.run_id, organization_id=job.organization_id, lock=True
                )
                if current.status != "RUNNING":
                    return
                for event in trail.events:
                    if event.event is not AuditEventType.RUN_SUCCEEDED:
                        work.audit_events.append(event)
                message = {
                    "EXECUTION_CANCELLED": "Reconciliation execution was cancelled.",
                    "EXECUTION_TIMEOUT": "Reconciliation execution exceeded its timeout.",
                }.get(code, "Reconciliation execution failed.")
                work.runs.transition(
                    job.run_id,
                    "FAILED",
                    error_code=code,
                    error_message=message,
                    organization_id=job.organization_id,
                )
