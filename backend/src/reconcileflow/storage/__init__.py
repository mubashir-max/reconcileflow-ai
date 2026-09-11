"""Secure file-storage services."""

from pathlib import Path

from .base import (
    FileStorage,
    InvalidStorageKeyError,
    StorageError,
    StorageNotFoundError,
    StorageObjectMetadata,
    StorageOperationError,
    StoredUpload,
    UploadStream,
)
from .local import EmptyUploadError, LocalFileStorage, UnsupportedUploadError, UploadTooLargeError


def create_file_storage(
    provider: str, *, directory: Path, max_size_bytes: int
) -> FileStorage:
    """Build a configured provider while rejecting unsupported names early."""
    if provider == "local":
        return LocalFileStorage(directory, max_size_bytes)
    raise ValueError("unsupported file storage provider")

__all__ = [
    "EmptyUploadError",
    "FileStorage",
    "InvalidStorageKeyError",
    "LocalFileStorage",
    "StorageError",
    "StorageNotFoundError",
    "StorageObjectMetadata",
    "StorageOperationError",
    "StoredUpload",
    "UnsupportedUploadError",
    "UploadTooLargeError",
    "UploadStream",
    "create_file_storage",
]
