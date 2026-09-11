"""Polling worker service with short, explicit database transactions."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from reconcileflow.persistence import (
    BackgroundJobStatus,
    PersistenceUnitOfWork,
)


logger = logging.getLogger(__name__)
SessionProvider = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True, slots=True)
class WorkerJob:
    """Non-secret job identifiers passed to a processor outside a transaction."""

    id: uuid.UUID
    organization_id: uuid.UUID
    run_id: uuid.UUID
    attempt_count: int
    max_attempts: int
    timeout_seconds: int
    deadline_at: datetime


class JobCancelled(RuntimeError):
    """Stop processing after the persisted job receives a cancellation request."""


class JobTimedOut(RuntimeError):
    """Stop processing after the persisted execution deadline is reached."""


class JobProcessor(Protocol):
    def __call__(self, job: WorkerJob, context: WorkerContext) -> None: ...


class WorkerContext:
    """Allow processors to report progress, renew their lease, and detect cancellation."""

    def __init__(
        self,
        session_provider: SessionProvider,
        worker_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_provider = session_provider
        self._worker_id = worker_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def checkpoint(
        self,
        job: WorkerJob,
        *,
        progress_percentage: int,
        status_message: str | None = None,
        at: datetime | None = None,
    ) -> None:
        checkpoint_at = self._utc(at or self._clock())
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                work.workers.heartbeat(self._worker_id, at=checkpoint_at)
                record = work.background_jobs.heartbeat(
                    job.id,
                    organization_id=job.organization_id,
                    worker_id=self._worker_id,
                    at=checkpoint_at,
                )
                work.background_jobs.update_progress(
                    job.id,
                    organization_id=job.organization_id,
                    progress_percentage=progress_percentage,
                    status_message=status_message,
                )
                cancellation_requested = (
                    record.status == BackgroundJobStatus.CANCEL_REQUESTED.value
                )
                deadline_at = record.deadline_at
        if cancellation_requested:
            raise JobCancelled("background job cancellation requested")
        if deadline_at is not None and checkpoint_at >= self._utc(deadline_at):
            raise JobTimedOut("background job execution deadline exceeded")

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class BackgroundWorker:
    """Claim one job at a time and delegate domain work to an injected processor."""

    def __init__(
        self,
        *,
        session_provider: SessionProvider,
        processor: JobProcessor,
        worker_id: str,
        poll_interval_seconds: float = 2.0,
        stale_timeout_seconds: int = 300,
        retry_delay_seconds: int = 30,
        priority_aging_seconds: int = 300,
        organization_id: uuid.UUID | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        worker_id = worker_id.strip()
        if not worker_id or len(worker_id) > 200:
            raise ValueError("worker_id must contain between 1 and 200 characters")
        if poll_interval_seconds < 0.1:
            raise ValueError("poll_interval_seconds must be at least 0.1")
        if stale_timeout_seconds < 30:
            raise ValueError("stale_timeout_seconds must be at least 30")
        if retry_delay_seconds < 1:
            raise ValueError("retry_delay_seconds must be positive")
        if priority_aging_seconds < 30:
            raise ValueError("priority_aging_seconds must be at least 30")
        self._session_provider = session_provider
        self._processor = processor
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._stale_timeout = timedelta(seconds=stale_timeout_seconds)
        self._retry_delay = timedelta(seconds=retry_delay_seconds)
        self._priority_aging_seconds = priority_aging_seconds
        self._organization_id = organization_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._context = WorkerContext(session_provider, worker_id, self._clock)

    def run_once(self) -> bool:
        """Recover stale leases, then process at most one eligible job."""
        now = self._now()
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                work.workers.heartbeat(self._worker_id, at=now)
                recovered = work.background_jobs.recover_stale(
                    stale_before=now - self._stale_timeout,
                    at=now,
                )
                record = work.background_jobs.claim_next(
                    worker_id=self._worker_id,
                    at=now,
                    organization_id=self._organization_id,
                    priority_aging_seconds=self._priority_aging_seconds,
                )
                job = None if record is None else WorkerJob(
                    id=record.id,
                    organization_id=record.organization_id,
                    run_id=record.run_id,
                    attempt_count=record.attempt_count,
                    max_attempts=record.max_attempts,
                    timeout_seconds=record.timeout_seconds,
                    deadline_at=self._utc(record.deadline_at),
                )
        if recovered:
            logger.info("Recovered %d interrupted background job(s)", recovered)
        if job is None:
            return False

        logger.info("Claimed a background job")
        try:
            self._processor(job, self._context)
        except JobCancelled:
            self._finish_cancelled(job)
            logger.info("Cancelled a background job")
        except JobTimedOut:
            self._finish_timed_out(job)
            logger.warning("A background job exceeded its execution deadline")
        except Exception:
            self._finish_failed(job)
            logger.warning("A background job failed safely")
        else:
            self._finish_successfully(job)
            logger.info("Completed a background job")
        return True

    def run_forever(self, stop_event: threading.Event) -> None:
        """Poll until shutdown is requested, without delaying signal handling."""
        logger.info("Background worker started")
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                work.workers.heartbeat(self._worker_id, at=self._now())
        try:
            while not stop_event.is_set():
                processed = self.run_once()
                if not processed:
                    stop_event.wait(self._poll_interval_seconds)
        finally:
            with self._session_provider() as session:
                with PersistenceUnitOfWork(session) as work:
                    work.workers.stop(self._worker_id, at=self._now())
            logger.info("Background worker stopped")

    def _finish_successfully(self, job: WorkerJob) -> None:
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                record = work.background_jobs.get(
                    job.id, organization_id=job.organization_id, lock=True
                )
                if record.status == BackgroundJobStatus.CANCEL_REQUESTED.value:
                    work.background_jobs.complete(
                        job.id,
                        BackgroundJobStatus.CANCELLED,
                        organization_id=job.organization_id,
                        at=self._now(),
                    )
                else:
                    work.background_jobs.complete(
                        job.id,
                        BackgroundJobStatus.SUCCEEDED,
                        organization_id=job.organization_id,
                        at=self._now(),
                    )

    def _finish_cancelled(self, job: WorkerJob) -> None:
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                work.background_jobs.complete(
                    job.id,
                    BackgroundJobStatus.CANCELLED,
                    organization_id=job.organization_id,
                    at=self._now(),
                )

    def _finish_failed(self, job: WorkerJob) -> None:
        now = self._now()
        retry_at = now + self._retry_delay if job.attempt_count < job.max_attempts else None
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                work.background_jobs.complete(
                    job.id,
                    BackgroundJobStatus.FAILED,
                    organization_id=job.organization_id,
                    at=now,
                    retry_at=retry_at,
                    failure_code="WORKER_PROCESSING_FAILED",
                    failure_message="Background job processing failed.",
                )

    def _finish_timed_out(self, job: WorkerJob) -> None:
        now = self._now()
        retry_at = now + self._retry_delay if job.attempt_count < job.max_attempts else None
        with self._session_provider() as session:
            with PersistenceUnitOfWork(session) as work:
                record = work.background_jobs.get(
                    job.id, organization_id=job.organization_id, lock=True
                )
                if record.status == BackgroundJobStatus.CANCEL_REQUESTED.value:
                    work.background_jobs.complete(
                        job.id,
                        BackgroundJobStatus.CANCELLED,
                        organization_id=job.organization_id,
                        at=now,
                    )
                else:
                    work.background_jobs.complete(
                        job.id,
                        BackgroundJobStatus.FAILED,
                        organization_id=job.organization_id,
                        at=now,
                        retry_at=retry_at,
                        failure_code="JOB_TIMEOUT",
                        failure_message="Background job exceeded its execution timeout.",
                    )

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            raise ValueError("claimed background job must have an execution deadline")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return a timezone-aware timestamp")
        return value.astimezone(UTC)
