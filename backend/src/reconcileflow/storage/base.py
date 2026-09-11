"""Provider-independent contracts for private reconciliation file storage."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable
from datetime import datetime


class StorageError(Exception):
    """Base error whose message is safe to expose to controlled callers."""


class StorageNotFoundError(StorageError):
    """The requested opaque object key does not exist."""


class InvalidStorageKeyError(StorageError, ValueError):
    """An object key failed strict traversal-safe validation."""


class StorageOperationError(StorageError):
    """A provider operation failed without exposing provider internals."""


class PresigningNotSupportedError(StorageError):
    """The selected provider cannot issue direct-access URLs."""


@dataclass(frozen=True, slots=True)
class StoredUpload:
    storage_key: str
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class StorageObjectMetadata:
    storage_key: str
    size_bytes: int
    content_type: str | None = None
    checksum_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StorageObjectCandidate:
    storage_key: str
    last_modified: datetime


class UploadStream(Protocol):
    """Framework-neutral asynchronous upload stream."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def close(self) -> None: ...


@runtime_checkable
class FileStorage(Protocol):
    """Minimal private-object contract implemented by every provider."""

    max_size_bytes: int

    async def save(
        self, upload: UploadStream, *, namespace: str | None = None
    ) -> StoredUpload: ...

    def open(self, storage_key: str) -> BinaryIO: ...

    def exists(self, storage_key: str) -> bool: ...

    def stat(self, storage_key: str) -> StorageObjectMetadata: ...

    def delete(self, storage_key: str) -> None: ...

    def materialize(self, storage_key: str) -> AbstractContextManager[Path]: ...

    def create_upload_url(
        self, *, namespace: str, filename: str, content_type: str,
        checksum_sha256: str | None = None, expires_seconds: int
    ) -> tuple[str, str, dict[str, str]]: ...

    def create_download_url(self, storage_key: str, *, expires_seconds: int) -> str: ...

    def belongs_to_namespace(self, storage_key: str, *, namespace: str) -> bool: ...

    def inspect_materialized(
        self, path: Path, *, original_filename: str, storage_key: str
    ) -> StoredUpload: ...

    def list_older_than(
        self, *, namespace: str, cutoff: datetime, limit: int
    ) -> list[StorageObjectCandidate]: ...
