"""Command-line entry point for safe database maintenance."""

from __future__ import annotations

import argparse
import logging

from reconcileflow.api.config import APISettings
from reconcileflow.persistence import Database
from reconcileflow.storage import create_file_storage

from .cleanup import RetentionCleanup
from .orphan_cleanup import AbandonedUploadCleanup
from .storage_integrity import StorageIntegrityVerifier


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m reconcileflow.maintenance")
    parser.add_argument("command", choices=("cleanup", "cleanup-uploads", "verify-storage"))
    parser.add_argument(
        "--dry-run", action="store_true", help="report eligible counts without deleting"
    )
    parser.add_argument(
        "--repair", action="store_true", help="repair safe storage inconsistencies explicitly"
    )
    arguments = parser.parse_args()
    settings = APISettings()
    logging.basicConfig(level=getattr(logging, settings.log_level))
    database = Database(settings)
    try:
        if arguments.command in {"cleanup-uploads", "verify-storage"}:
            storage = create_file_storage(
                settings.storage_provider,
                directory=settings.upload_directory,
                max_size_bytes=settings.max_upload_size_bytes,
                s3_bucket=settings.s3_bucket,
                s3_region=settings.s3_region,
                s3_endpoint_url=settings.s3_endpoint_url,
                s3_access_key_id=settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None,
                s3_secret_access_key=settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None,
                s3_use_path_style=settings.s3_use_path_style,
                s3_connect_timeout_seconds=settings.s3_connect_timeout_seconds,
                s3_read_timeout_seconds=settings.s3_read_timeout_seconds,
                s3_auto_create_bucket=False,
            )
            if arguments.command == "verify-storage":
                result = StorageIntegrityVerifier(
                    session_provider=database.session,
                    storage=storage,
                    grace_hours=settings.storage_integrity_grace_hours,
                    batch_size=settings.storage_integrity_batch_size,
                ).run(repair=arguments.repair and not arguments.dry_run)
                logging.getLogger(__name__).info(
                    "storage_integrity repair=%s checked_records=%d missing_objects=%d "
                    "mismatched_objects=%d abandoned_objects=%d usage_mismatches=%d "
                    "deleted_objects=%d repaired_usage_counters=%d",
                    result.repair, result.checked_records, result.missing_objects,
                    result.mismatched_objects, result.abandoned_objects,
                    result.usage_mismatches, result.deleted_objects,
                    result.repaired_usage_counters,
                )
                return
            result = AbandonedUploadCleanup(
                session_provider=database.session,
                storage=storage,
                retention_hours=settings.abandoned_upload_retention_hours,
                batch_size=settings.cleanup_batch_size,
            ).run(dry_run=arguments.dry_run)
            logging.getLogger(__name__).info(
                "abandoned_upload_cleanup dry_run=%s eligible_objects=%d deleted_objects=%d",
                result.dry_run, result.eligible_objects, result.deleted_objects,
            )
            return
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
