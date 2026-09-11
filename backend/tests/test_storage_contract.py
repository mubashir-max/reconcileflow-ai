from __future__ import annotations

import io

import pytest
from fastapi import UploadFile

from reconcileflow.storage import (
    FileStorage,
    InvalidStorageKeyError,
    LocalFileStorage,
    StorageNotFoundError,
    create_file_storage,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_local_provider_implements_complete_streaming_contract(tmp_path):
    storage = create_file_storage(
        "local", directory=tmp_path / "private", max_size_bytes=1024
    )
    assert isinstance(storage, FileStorage)
    stored = await storage.save(
        UploadFile(filename="../../customer data.csv", file=io.BytesIO(b"id,amount\n1,10\n")),
        namespace="00000000-0000-0000-0000-000000000001",
    )

    assert stored.original_filename == "customer data.csv"
    assert "00000000" not in stored.storage_key
    assert "/" not in stored.storage_key and "\\" not in stored.storage_key
    assert storage.exists(stored.storage_key)
    assert storage.stat(stored.storage_key).size_bytes == stored.size_bytes
    with storage.open(stored.storage_key) as source:
        assert source.read() == b"id,amount\n1,10\n"
    with storage.materialize(stored.storage_key) as path:
        assert path.read_bytes() == b"id,amount\n1,10\n"

    storage.delete(stored.storage_key)
    storage.delete(stored.storage_key)
    assert not storage.exists(stored.storage_key)


@pytest.mark.parametrize(
    "key",
    (
        "",
        ".hidden",
        "../escape.csv",
        "folder/file.csv",
        "folder\\file.csv",
        "C:\\secret.csv",
        "a" * 32 + ".exe",
        "A" * 32 + ".csv",
    ),
)
def test_local_provider_rejects_unsafe_object_keys(tmp_path, key):
    storage = LocalFileStorage(tmp_path / "private", 1024)
    with pytest.raises(InvalidStorageKeyError, match="invalid storage key"):
        storage.exists(key)


def test_missing_objects_and_unsupported_providers_fail_safely(tmp_path):
    storage = LocalFileStorage(tmp_path / "private", 1024)
    with pytest.raises(StorageNotFoundError) as error:
        storage.open("a" * 32 + ".csv")
    assert str(tmp_path) not in str(error.value)
    with pytest.raises(ValueError, match="unsupported file storage provider"):
        create_file_storage("s3", directory=tmp_path, max_size_bytes=1024)
