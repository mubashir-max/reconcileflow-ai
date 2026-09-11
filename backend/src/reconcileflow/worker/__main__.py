"""Run the standalone ReconcileFlow background worker."""

from __future__ import annotations

import logging
import signal
import threading

from reconcileflow.api.config import APISettings
from reconcileflow.persistence import Database
from reconcileflow.storage import LocalFileStorage

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
            storage=LocalFileStorage(
                settings.upload_directory, settings.max_upload_size_bytes
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
