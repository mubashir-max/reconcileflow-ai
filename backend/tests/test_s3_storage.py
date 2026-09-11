from __future__ import annotations

import io

import pytest
from botocore.exceptions import ClientError
from fastapi import UploadFile

from reconcileflow.storage import (
    InvalidStorageKeyError,
    S3FileStorage,
    StorageNotFoundError,
    StorageOperationError,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_args: dict[str, object] | None = None

    def upload_fileobj(self, source, bucket, key, ExtraArgs):
        self.objects[key] = source.read()
        self.upload_args = ExtraArgs

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _missing("GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _missing("HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)

    def head_bucket(self, *, Bucket):
        return {}


def _missing(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "sensitive provider detail"}}, operation)


def _storage(monkeypatch, client: FakeS3Client | None = None) -> S3FileStorage:
    fake = client or FakeS3Client()
    monkeypatch.setattr("reconcileflow.storage.s3.boto3.client", lambda *args, **kwargs: fake)
    return S3FileStorage(
        bucket="private-test-bucket",
        region="us-east-1",
        endpoint_url="http://localhost:9000",
        access_key_id="test-user",
        secret_access_key="test-secret",
        use_path_style=True,
        connect_timeout_seconds=2,
        read_timeout_seconds=5,
        max_size_bytes=1024,
    )


@pytest.mark.anyio
async def test_s3_provider_implements_private_storage_contract(monkeypatch):
    client = FakeS3Client()
    storage = _storage(monkeypatch, client)
    payload = b"id,amount\n1,10\n"
    stored = await storage.save(
        UploadFile(filename="customer.csv", file=io.BytesIO(payload)),
        namespace="tenant-id",
    )

    assert storage.exists(stored.storage_key)
    assert storage.stat(stored.storage_key).size_bytes == len(payload)
    assert client.upload_args == {
        "ContentType": "text/csv",
        "Metadata": {"checksum-sha256": stored.checksum_sha256},
    }
    assert "ACL" not in client.upload_args
    with storage.open(stored.storage_key) as source:
        assert source.read() == payload
    with storage.materialize(stored.storage_key) as path:
        materialized = path
        assert path.read_bytes() == payload
    assert not materialized.exists()

    storage.delete(stored.storage_key)
    storage.delete(stored.storage_key)
    assert not storage.exists(stored.storage_key)


def test_s3_provider_rejects_keys_and_sanitizes_provider_errors(monkeypatch):
    storage = _storage(monkeypatch)
    with pytest.raises(InvalidStorageKeyError):
        storage.exists("../secret.csv")
    with pytest.raises(StorageNotFoundError) as missing:
        storage.open("a" * 32 + ".csv")
    assert "sensitive" not in str(missing.value)

    client = FakeS3Client()
    client.head_object = lambda **kwargs: (_ for _ in ()).throw(
        ClientError({"Error": {"Code": "500", "Message": "test-secret"}}, "HeadObject")
    )
    storage = _storage(monkeypatch, client)
    with pytest.raises(StorageOperationError) as failed:
        storage.exists("a" * 32 + ".csv")
    assert "test-secret" not in str(failed.value)
