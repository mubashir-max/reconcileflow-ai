"""Bounded, atomic local storage for uploaded CSV and XLSX files."""

from __future__ import annotations

import hashlib
import codecs
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile


class UploadStorageError(Exception):
    """Base class for expected and safely reportable upload failures."""


class EmptyUploadError(UploadStorageError):
    pass


class UploadTooLargeError(UploadStorageError):
    pass


class UnsupportedUploadError(UploadStorageError):
    pass


@dataclass(frozen=True, slots=True)
class StoredUpload:
    storage_key: str
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str


class LocalFileStorage:
    """Store validated uploads under server-generated names within one directory."""

    _CHUNK_SIZE = 64 * 1024
    _CONTENT_TYPES = {".csv": "text/csv", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    def __init__(self, directory: Path, max_size_bytes: int) -> None:
        self.directory = directory.resolve()
        self.max_size_bytes = max_size_bytes

    async def save(self, upload: UploadFile) -> StoredUpload:
        original_filename, extension = self._validated_filename(upload.filename)
        self.directory.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        temporary = self.directory / f".{identifier}.part"
        final = self.directory / f"{identifier}{extension}"
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
        except Exception:
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def delete(self, storage_key: str) -> None:
        self.resolve(storage_key, require_exists=False).unlink(missing_ok=True)

    def resolve(self, storage_key: str, *, require_exists: bool = True) -> Path:
        """Resolve a server-generated key without allowing traversal."""
        candidate = self.directory / storage_key
        if candidate.name != storage_key or candidate.parent.resolve() != self.directory:
            raise ValueError("invalid storage key")
        if require_exists and not candidate.is_file():
            raise FileNotFoundError("stored upload is unavailable")
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
