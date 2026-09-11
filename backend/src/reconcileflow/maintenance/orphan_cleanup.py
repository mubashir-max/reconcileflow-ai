"""Tenant-scoped cleanup for abandoned direct-upload objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from reconcileflow.persistence import PersistenceUnitOfWork
from reconcileflow.storage import FileStorage


@dataclass(frozen=True, slots=True)
class OrphanCleanupResult:
    eligible_objects: int
    deleted_objects: int
    dry_run: bool


class AbandonedUploadCleanup:
    """Delete expired tenant objects that have no source-file reference."""

    def __init__(
        self, *, session_provider: Callable[[], Session], storage: FileStorage,
        retention_hours: int, batch_size: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if retention_hours < 1 or batch_size < 1:
            raise ValueError("retention_hours and batch_size must be positive")
        self._session_provider = session_provider
        self._storage = storage
        self._retention_hours = retention_hours
        self._batch_size = batch_size
        self._clock = clock

    def run(self, *, dry_run: bool = False) -> OrphanCleanupResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("cleanup clock must return a timezone-aware timestamp")
        cutoff = now.astimezone(UTC) - timedelta(hours=self._retention_hours)
        with self._session_provider() as session:
            work = PersistenceUnitOfWork(session)
            organization_ids = work.organizations.list_ids()
        eligible = 0
        deleted = 0
        for organization_id in organization_ids:
            candidates = self._storage.list_older_than(
                namespace=str(organization_id), cutoff=cutoff, limit=self._batch_size
            )
            with self._session_provider() as session:
                referenced = PersistenceUnitOfWork(session).source_files.referenced_storage_keys(
                    organization_id=organization_id
                )
            for candidate in candidates:
                if candidate.storage_key in referenced:
                    continue
                eligible += 1
                if not dry_run:
                    self._storage.delete(candidate.storage_key)
                    deleted += 1
        return OrphanCleanupResult(eligible, deleted, dry_run)
