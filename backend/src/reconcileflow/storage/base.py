"""Provider-independent contracts for private reconciliation file storage."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable


class StorageError(Exception):
    """Base error whose message is safe to expose to controlled callers."""


class StorageNotFoundError(StorageError):
    """The requested opaque object key does not exist."""


class InvalidStorageKeyError(StorageError, ValueError):
    """An object key failed strict traversal-safe validation."""


class StorageOperationError(StorageError):
    """A provider operation failed without exposing provider internals."""


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


class UploadStream(Protocol):
    """Framework-neutral asynchronous upload stream."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def close(self) -> None: ...


@runtime_checkable
class FileStorage(Protocol):
    """Minimal private-object contract implemented by every provider."""

    async def save(
        self, upload: UploadStream, *, namespace: str | None = None
    ) -> StoredUpload: ...

    def open(self, storage_key: str) -> BinaryIO: ...

    def exists(self, storage_key: str) -> bool: ...

    def stat(self, storage_key: str) -> StorageObjectMetadata: ...

    def delete(self, storage_key: str) -> None: ...

    def materialize(self, storage_key: str) -> AbstractContextManager[Path]: ...

    def resolve(self, storage_key: str, *, require_exists: bool = True) -> Path: ...
