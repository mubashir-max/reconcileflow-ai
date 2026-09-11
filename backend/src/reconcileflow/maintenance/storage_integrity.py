"""Provider-independent storage integrity verification and bounded repair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from reconcileflow.persistence import PersistenceUnitOfWork
from reconcileflow.storage import FileStorage, StorageNotFoundError


@dataclass(frozen=True, slots=True)
class StorageIntegrityResult:
    checked_records: int
    missing_objects: int
    mismatched_objects: int
    abandoned_objects: int
    usage_mismatches: int
    deleted_objects: int
    repaired_usage_counters: int
    repair: bool


class StorageIntegrityVerifier:
    """Compare tenant metadata with private storage without returning identifiers."""

    def __init__(
        self, *, session_provider: Callable[[], Session], storage: FileStorage,
        grace_hours: int, batch_size: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if grace_hours < 1 or batch_size < 1:
            raise ValueError("grace_hours and batch_size must be positive")
        self._session_provider = session_provider
        self._storage = storage
        self._grace_hours = grace_hours
        self._batch_size = batch_size
        self._clock = clock

    def run(self, *, repair: bool = False) -> StorageIntegrityResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("verification clock must return a timezone-aware timestamp")
        cutoff = now.astimezone(UTC) - timedelta(hours=self._grace_hours)
        with self._session_provider() as session:
            organization_ids = PersistenceUnitOfWork(session).organizations.list_ids()

        checked = missing = mismatched = abandoned = usage_mismatches = 0
        deleted = repaired_usage = 0
        for organization_id in organization_ids:
            with self._session_provider() as session:
                work = PersistenceUnitOfWork(session)
                organization = work.organizations.get(organization_id)
                records = work.source_files.list_stored_for_organization(
                    organization_id=organization_id, limit=self._batch_size
                )
                record_data = [
                    (record.storage_key, record.size_bytes, record.checksum_sha256)
                    for record in records
                ]
                referenced = work.source_files.referenced_storage_keys(organization_id=organization_id)
                expected_usage = work.source_files.total_size_for_organization(organization_id=organization_id)
                if organization.storage_used_bytes != expected_usage:
                    usage_mismatches += 1
                    if repair:
                        organization.storage_used_bytes = expected_usage
                        session.commit()
                        repaired_usage += 1

            for storage_key, size_bytes, checksum_sha256 in record_data:
                checked += 1
                try:
                    metadata = self._storage.stat(storage_key)
                except StorageNotFoundError:
                    missing += 1
                    continue
                if metadata.size_bytes != size_bytes or (
                    metadata.checksum_sha256 is not None
                    and metadata.checksum_sha256 != checksum_sha256
                ):
                    mismatched += 1

            candidates = self._storage.list_older_than(
                namespace=str(organization_id), cutoff=cutoff, limit=self._batch_size
            )
            for candidate in candidates:
                if candidate.storage_key in referenced:
                    continue
                abandoned += 1
                if repair:
                    self._storage.delete(candidate.storage_key)
                    deleted += 1

        return StorageIntegrityResult(
            checked, missing, mismatched, abandoned, usage_mismatches,
            deleted, repaired_usage, repair,
        )
