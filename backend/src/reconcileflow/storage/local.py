"""Bounded, atomic local storage for uploaded CSV and XLSX files."""

from __future__ import annotations

import hashlib
import codecs
import os
import re
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from .base import (
    InvalidStorageKeyError,
    StorageNotFoundError,
    StorageObjectMetadata,
    StorageOperationError,
    StoredUpload,
    UploadStream,
    PresigningNotSupportedError,
)


class UploadStorageError(StorageOperationError):
    """Base class for expected and safely reportable upload failures."""


class EmptyUploadError(UploadStorageError):
    pass


class UploadTooLargeError(UploadStorageError):
    pass


class UnsupportedUploadError(UploadStorageError):
    pass


class LocalFileStorage:
    """Store validated uploads under server-generated names within one directory."""

    _CHUNK_SIZE = 64 * 1024
    _CONTENT_TYPES = {".csv": "text/csv", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    _STORAGE_KEY = re.compile(r"(?:[0-9a-f]{16}-)?[0-9a-f]{32}\.(?:csv|xlsx)\Z")

    def __init__(self, directory: Path, max_size_bytes: int) -> None:
        self.directory = directory.resolve()
        self.max_size_bytes = max_size_bytes

    async def save(
        self, upload: UploadStream, *, namespace: str | None = None
    ) -> StoredUpload:
        original_filename, extension = self._validated_filename(upload.filename)
        self.directory.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        prefix = f"{hashlib.sha256(namespace.encode('utf-8')).hexdigest()[:16]}-" if namespace else ""
        temporary = self.directory / f".{identifier}.part"
        final = self.directory / f"{prefix}{identifier}{extension}"
        digest = hashlib.sha256()
        size = 0
        first_chunk = b""
        try:
            with temporary.open("xb") as output:
                while chunk := await upload.read(self._CHUNK_SIZE):
                    if not first_chunk:
                        first_chunk = chunk
                    size += len(chunk)
                    if size > self.max_size_bytes:
                        raise UploadTooLargeError("upload exceeds configured size limit")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size == 0:
                raise EmptyUploadError("upload is empty")
            self._validate_contents(temporary, extension, first_chunk)
            temporary.replace(final)
            return StoredUpload(
                storage_key=final.name,
                original_filename=original_filename,
                content_type=self._CONTENT_TYPES[extension],
                size_bytes=size,
                checksum_sha256=digest.hexdigest(),
            )
        except (EmptyUploadError, UploadTooLargeError, UnsupportedUploadError):
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise
        except OSError as error:
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise StorageOperationError("the storage operation could not be completed") from error
        finally:
            await upload.close()

    def delete(self, storage_key: str) -> None:
        try:
            self.resolve(storage_key, require_exists=False).unlink(missing_ok=True)
        except OSError as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def open(self, storage_key: str) -> BinaryIO:
        try:
            return self.resolve(storage_key).open("rb")
        except OSError as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def exists(self, storage_key: str) -> bool:
        return self.resolve(storage_key, require_exists=False).is_file()

    def stat(self, storage_key: str) -> StorageObjectMetadata:
        try:
            path = self.resolve(storage_key)
            return StorageObjectMetadata(storage_key=storage_key, size_bytes=path.stat().st_size)
        except OSError as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    @contextmanager
    def materialize(self, storage_key: str) -> Iterator[Path]:
        yield self.resolve(storage_key)

    def create_upload_url(
        self, *, namespace: str, filename: str, content_type: str,
        checksum_sha256: str | None = None, expires_seconds: int
    ) -> tuple[str, str, dict[str, str]]:
        raise PresigningNotSupportedError("direct object access is unavailable")

    def create_download_url(self, storage_key: str, *, expires_seconds: int) -> str:
        raise PresigningNotSupportedError("direct object access is unavailable")

    def belongs_to_namespace(self, storage_key: str, *, namespace: str) -> bool:
        self.resolve(storage_key, require_exists=False)
        prefix = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
        return storage_key.startswith(f"{prefix}-")

    def inspect_materialized(
        self, path: Path, *, original_filename: str, storage_key: str
    ) -> StoredUpload:
        safe_name, extension = self._validated_filename(original_filename)
        try:
            size = path.stat().st_size
            if size == 0:
                raise EmptyUploadError("upload is empty")
            if size > self.max_size_bytes:
                raise UploadTooLargeError("upload exceeds configured size limit")
            digest = hashlib.sha256()
            first_chunk = b""
            with path.open("rb") as source:
                while chunk := source.read(self._CHUNK_SIZE):
                    if not first_chunk:
                        first_chunk = chunk
                    digest.update(chunk)
            self._validate_contents(path, extension, first_chunk)
            return StoredUpload(
                storage_key=storage_key, original_filename=safe_name,
                content_type=self._CONTENT_TYPES[extension], size_bytes=size,
                checksum_sha256=digest.hexdigest(),
            )
        except (EmptyUploadError, UploadTooLargeError, UnsupportedUploadError):
            raise
        except OSError as error:
            raise StorageOperationError("the storage operation could not be completed") from error

    def resolve(self, storage_key: str, *, require_exists: bool = True) -> Path:
        """Resolve a server-generated key without allowing traversal."""
        candidate = self.directory / storage_key
        if (
            self._STORAGE_KEY.fullmatch(storage_key) is None
            or candidate.name != storage_key
            or candidate.parent.resolve() != self.directory
        ):
            raise InvalidStorageKeyError("invalid storage key")
        if require_exists and not candidate.is_file():
            raise StorageNotFoundError("stored object is unavailable")
        return candidate

    @classmethod
    def _validated_filename(cls, supplied: str | None) -> tuple[str, str]:
        if not supplied:
            raise UnsupportedUploadError("a filename with a supported extension is required")
        basename = Path(supplied.replace("\\", "/")).name
        basename = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()
        extension = Path(basename).suffix.lower()
        if extension not in cls._CONTENT_TYPES:
            raise UnsupportedUploadError("only CSV and XLSX uploads are supported")
        stem = Path(basename).stem[: 255 - len(extension)].strip(" .") or "upload"
        return f"{stem}{extension}", extension

    def _validate_contents(self, path: Path, extension: str, first_chunk: bytes) -> None:
        if extension == ".xlsx":
            if not first_chunk.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(path):
                raise UnsupportedUploadError("file contents are not a valid XLSX container")
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise UnsupportedUploadError("file contents are not a valid XLSX workbook")
                if sum(item.file_size for item in archive.infolist()) > self.max_size_bytes * 20:
                    raise UnsupportedUploadError("XLSX expanded contents exceed the safe limit")
            return
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        try:
            with path.open("rb") as source:
                while chunk := source.read(self._CHUNK_SIZE):
                    if b"\x00" in chunk:
                        raise UnsupportedUploadError("CSV uploads must contain text data")
                    decoder.decode(chunk)
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as error:
            raise UnsupportedUploadError("CSV uploads must use UTF-8 text") from error
