"""Command-line entry point for safe database maintenance."""

from __future__ import annotations

import argparse
import logging

from reconcileflow.api.config import APISettings
from reconcileflow.persistence import Database

from .cleanup import RetentionCleanup


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m reconcileflow.maintenance")
    parser.add_argument("command", choices=("cleanup",))
    parser.add_argument(
        "--dry-run", action="store_true", help="report eligible counts without deleting"
    )
    arguments = parser.parse_args()
    settings = APISettings()
    logging.basicConfig(level=getattr(logging, settings.log_level))
    database = Database(settings)
    try:
        result = RetentionCleanup(
            session_provider=database.session,
            succeeded_days=settings.succeeded_job_retention_days,
            failed_days=settings.failed_job_retention_days,
            cancelled_days=settings.cancelled_job_retention_days,
            worker_days=settings.worker_record_retention_days,
            batch_size=settings.cleanup_batch_size,
        ).run(dry_run=arguments.dry_run)
        logging.getLogger(__name__).info(
            "retention_cleanup dry_run=%s eligible_jobs=%d deleted_jobs=%d "
            "eligible_workers=%d deleted_workers=%d",
            result.dry_run,
            result.eligible_jobs,
            result.deleted_jobs,
            result.eligible_workers,
            result.deleted_workers,
        )
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
