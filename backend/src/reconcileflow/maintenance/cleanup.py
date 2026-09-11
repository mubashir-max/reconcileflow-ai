"""Bounded retention cleanup for operational queue records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from reconcileflow.persistence import BackgroundJobStatus, PersistenceUnitOfWork


SessionProvider = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """Aggregate cleanup counts that contain no record identifiers."""

    eligible_jobs: int
    deleted_jobs: int
    eligible_workers: int
    deleted_workers: int
    dry_run: bool


class RetentionCleanup:
    """Remove expired operational records without touching reconciliation history."""

    def __init__(
        self,
        *,
        session_provider: SessionProvider,
        succeeded_days: int,
        failed_days: int,
        cancelled_days: int,
        worker_days: int,
        batch_size: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        values = (succeeded_days, failed_days, cancelled_days, worker_days, batch_size)
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("retention values and batch_size must be positive integers")
        self._session_provider = session_provider
        self._retention_days = {
            BackgroundJobStatus.SUCCEEDED: succeeded_days,
            BackgroundJobStatus.FAILED: failed_days,
            BackgroundJobStatus.CANCELLED: cancelled_days,
        }
        self._worker_days = worker_days
        self._batch_size = batch_size
        self._clock = clock

    def run(self, *, dry_run: bool = False) -> CleanupResult:
        now = self._now()
        cutoffs = {
            status: now - timedelta(days=days)
            for status, days in self._retention_days.items()
        }
        worker_cutoff = now - timedelta(days=self._worker_days)
        with self._session_provider() as session:
            jobs = PersistenceUnitOfWork(session).background_jobs.count_expired_terminal(
                cutoffs=cutoffs
            )
            workers = PersistenceUnitOfWork(session).workers.count_expired(
                cutoff=worker_cutoff
            )
        if dry_run:
            return CleanupResult(jobs, 0, workers, 0, True)

        deleted_jobs = self._delete_jobs(cutoffs)
        deleted_workers = self._delete_workers(worker_cutoff)
        return CleanupResult(jobs, deleted_jobs, workers, deleted_workers, False)

    def _delete_jobs(self, cutoffs: dict[BackgroundJobStatus, datetime]) -> int:
        total = 0
        while True:
            with self._session_provider() as session:
                with PersistenceUnitOfWork(session) as work:
                    deleted = work.background_jobs.delete_expired_terminal(
                        cutoffs=cutoffs, limit=self._batch_size
                    )
            total += deleted
            if deleted < self._batch_size:
                return total

    def _delete_workers(self, cutoff: datetime) -> int:
        total = 0
        while True:
            with self._session_provider() as session:
                with PersistenceUnitOfWork(session) as work:
                    deleted = work.workers.delete_expired(
                        cutoff=cutoff, limit=self._batch_size
                    )
            total += deleted
            if deleted < self._batch_size:
                return total

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cleanup clock must return a timezone-aware timestamp")
        return value.astimezone(UTC)
