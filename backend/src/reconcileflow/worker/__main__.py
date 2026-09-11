"""Run the standalone ReconcileFlow background worker."""

from __future__ import annotations

import logging
import signal
import threading

from reconcileflow.api.config import APISettings
from reconcileflow.persistence import Database
from reconcileflow.storage import create_file_storage

from .reconciliation import ReconciliationJobProcessor
from .service import BackgroundWorker


def main() -> None:
    settings = APISettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = Database(settings)
    stop_event = threading.Event()

    def request_shutdown(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    worker = BackgroundWorker(
        session_provider=database.session,
        processor=ReconciliationJobProcessor(
            session_provider=database.session,
            storage=create_file_storage(
                settings.storage_provider,
                directory=settings.upload_directory,
                max_size_bytes=settings.max_upload_size_bytes,
                s3_bucket=settings.s3_bucket,
                s3_region=settings.s3_region,
                s3_endpoint_url=settings.s3_endpoint_url,
                s3_access_key_id=(
                    settings.s3_access_key_id.get_secret_value()
                    if settings.s3_access_key_id else None
                ),
                s3_secret_access_key=(
                    settings.s3_secret_access_key.get_secret_value()
                    if settings.s3_secret_access_key else None
                ),
                s3_use_path_style=settings.s3_use_path_style,
                s3_connect_timeout_seconds=settings.s3_connect_timeout_seconds,
                s3_read_timeout_seconds=settings.s3_read_timeout_seconds,
                s3_auto_create_bucket=settings.s3_auto_create_bucket,
            ),
        ),
        worker_id=settings.worker_id,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        stale_timeout_seconds=settings.worker_stale_timeout_seconds,
        retry_delay_seconds=settings.worker_retry_delay_seconds,
        priority_aging_seconds=settings.job_priority_aging_seconds,
    )
    try:
        worker.run_forever(stop_event)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
