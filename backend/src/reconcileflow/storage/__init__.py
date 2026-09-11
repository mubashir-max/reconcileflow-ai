"""Secure file-storage services."""

from pathlib import Path

from .base import (
    FileStorage,
    InvalidStorageKeyError,
    PresigningNotSupportedError,
    StorageError,
    StorageNotFoundError,
    StorageObjectMetadata,
    StorageObjectCandidate,
    StorageOperationError,
    StoredUpload,
    UploadStream,
)
from .local import EmptyUploadError, LocalFileStorage, UnsupportedUploadError, UploadTooLargeError
from .s3 import S3FileStorage


def create_file_storage(
    provider: str,
    *,
    directory: Path,
    max_size_bytes: int,
    s3_bucket: str | None = None,
    s3_region: str = "us-east-1",
    s3_endpoint_url: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    s3_use_path_style: bool = False,
    s3_connect_timeout_seconds: int = 5,
    s3_read_timeout_seconds: int = 30,
    s3_auto_create_bucket: bool = False,
) -> FileStorage:
    """Build a configured provider while rejecting unsupported names early."""
    if provider == "local":
        return LocalFileStorage(directory, max_size_bytes)
    if provider == "s3" and s3_bucket is not None:
        return S3FileStorage(
            bucket=s3_bucket,
            region=s3_region,
            endpoint_url=s3_endpoint_url,
            access_key_id=s3_access_key_id,
            secret_access_key=s3_secret_access_key,
            use_path_style=s3_use_path_style,
            connect_timeout_seconds=s3_connect_timeout_seconds,
            read_timeout_seconds=s3_read_timeout_seconds,
            max_size_bytes=max_size_bytes,
            auto_create_bucket=s3_auto_create_bucket,
        )
    raise ValueError("unsupported file storage provider")

__all__ = [
    "EmptyUploadError",
    "FileStorage",
    "InvalidStorageKeyError",
    "LocalFileStorage",
    "PresigningNotSupportedError",
    "S3FileStorage",
    "StorageError",
    "StorageNotFoundError",
    "StorageObjectMetadata",
    "StorageObjectCandidate",
    "StorageOperationError",
    "StoredUpload",
    "UnsupportedUploadError",
    "UploadTooLargeError",
    "UploadStream",
    "create_file_storage",
]
