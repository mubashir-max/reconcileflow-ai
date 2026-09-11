"""Private S3-compatible storage with bounded local materialization."""

from __future__ import annotations

import shutil
import tempfile
import hashlib
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from .base import (
    InvalidStorageKeyError,
    PresigningNotSupportedError,
    StorageNotFoundError,
    StorageObjectMetadata,
    StorageOperationError,
    StoredUpload,
    UploadStream,
)
from .local import LocalFileStorage


class S3FileStorage:
    """Store private objects through the S3 API without exposing provider details."""

    _CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        use_path_style: bool,
        connect_timeout_seconds: int,
        read_timeout_seconds: int,
        max_size_bytes: int,
        auto_create_bucket: bool = False,
    ) -> None:
        self.bucket = bucket
        self.max_size_bytes = max_size_bytes
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                connect_timeout=connect_timeout_seconds,
                read_timeout=read_timeout_seconds,
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path" if use_path_style else "virtual"},
            ),
        )
        if auto_create_bucket:
            self._ensure_bucket(region)

    async def save(
        self, upload: UploadStream, *, namespace: str | None = None
    ) -> StoredUpload:
        try:
            with tempfile.TemporaryDirectory(prefix="reconcileflow-storage-") as directory:
                staging = LocalFileStorage(Path(directory), self.max_size_bytes)
                stored = await staging.save(upload, namespace=namespace)
                with staging.open(stored.storage_key) as source:
                    self._client.upload_fileobj(
                        source,
                        self.bucket,
                        stored.storage_key,
                        ExtraArgs={
                            "ContentType": stored.content_type,
                            "Metadata": {"checksum-sha256": stored.checksum_sha256},
                        },
                    )
                return stored
        except StorageOperationError:
            raise
        except (BotoCoreError, ClientError, OSError) as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def open(self, storage_key: str) -> BinaryIO:
        self._validate_key(storage_key)
        try:
            return self._client.get_object(Bucket=self.bucket, Key=storage_key)["Body"]
        except ClientError as error:
            self._raise_client_error(error)
        except BotoCoreError as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def exists(self, storage_key: str) -> bool:
        self._validate_key(storage_key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except ClientError as error:
            if self._is_missing(error):
                return False
            self._raise_client_error(error)
        except BotoCoreError as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def stat(self, storage_key: str) -> StorageObjectMetadata:
        self._validate_key(storage_key)
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=storage_key)
            return StorageObjectMetadata(
                storage_key=storage_key, size_bytes=int(response["ContentLength"])
            )
        except ClientError as error:
            self._raise_client_error(error)
        except (BotoCoreError, KeyError, TypeError, ValueError) as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def delete(self, storage_key: str) -> None:
        self._validate_key(storage_key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=storage_key)
        except (BotoCoreError, ClientError) as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def create_upload_url(
        self, *, namespace: str, filename: str, content_type: str, expires_seconds: int
    ) -> tuple[str, str, dict[str, str]]:
        try:
            safe_name, extension = LocalFileStorage._validated_filename(filename)
            expected_type = LocalFileStorage._CONTENT_TYPES[extension]
            if content_type != expected_type:
                raise InvalidStorageKeyError("content type does not match the filename")
            prefix = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
            storage_key = f"{prefix}-{uuid.uuid4().hex}{extension}"
            response = self._client.generate_presigned_post(
                Bucket=self.bucket,
                Key=storage_key,
                Fields={"Content-Type": expected_type},
                Conditions=[
                    {"Content-Type": expected_type},
                    ["content-length-range", 1, self.max_size_bytes],
                ],
                ExpiresIn=expires_seconds,
            )
            return storage_key, str(response["url"]), {
                str(key): str(value) for key, value in response["fields"].items()
            }
        except (InvalidStorageKeyError, PresigningNotSupportedError):
            raise
        except (BotoCoreError, ClientError, KeyError, TypeError) as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def create_download_url(self, storage_key: str, *, expires_seconds: int) -> str:
        self._validate_key(storage_key)
        if not self.exists(storage_key):
            raise StorageNotFoundError("stored object is unavailable")
        try:
            return str(self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": storage_key},
                ExpiresIn=expires_seconds,
            ))
        except (BotoCoreError, ClientError) as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    @contextmanager
    def materialize(self, storage_key: str) -> Iterator[Path]:
        self._validate_key(storage_key)
        suffix = Path(storage_key).suffix
        with tempfile.TemporaryDirectory(prefix="reconcileflow-materialized-") as directory:
            path = Path(directory) / f"source{suffix}"
            try:
                with self.open(storage_key) as source, path.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=self._CHUNK_SIZE)
                yield path
            except StorageNotFoundError:
                raise
            except OSError as error:
                raise StorageOperationError("the storage operation could not be completed") from error

    def _ensure_bucket(self, region: str) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            if not self._is_missing(error):
                self._raise_client_error(error)
            parameters = {"Bucket": self.bucket}
            if region != "us-east-1":
                parameters["CreateBucketConfiguration"] = {"LocationConstraint": region}
            try:
                self._client.create_bucket(**parameters)
            except (BotoCoreError, ClientError) as create_error:
                raise StorageOperationError(
                    "the storage bucket could not be initialized"
                ) from create_error
        except BotoCoreError as error:
            raise StorageOperationError("the storage bucket could not be initialized") from error

    @staticmethod
    def _validate_key(storage_key: str) -> None:
        if LocalFileStorage._STORAGE_KEY.fullmatch(storage_key) is None:
            raise InvalidStorageKeyError("invalid storage key")

    @staticmethod
    def _is_missing(error: ClientError) -> bool:
        return str(error.response.get("Error", {}).get("Code", "")) in {
            "404", "NoSuchBucket", "NoSuchKey", "NotFound"
        }

    @classmethod
    def _raise_client_error(cls, error: ClientError) -> None:
        if cls._is_missing(error):
            raise StorageNotFoundError("stored object is unavailable") from error
        raise StorageOperationError("the storage operation could not be completed") from error
