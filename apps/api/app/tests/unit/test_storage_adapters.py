from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.storage import (
    LocalFilesystemStorageAdapter,
    MaterializedObject,
    S3CompatibleStorageAdapter,
    build_storage_adapter,
)


def test_build_storage_adapter_uses_local_filesystem_when_local_dir_present(tmp_path: Path) -> None:
    settings = Settings(local_storage_dir=str(tmp_path), storage_backend="local")

    adapter = build_storage_adapter(settings)

    assert isinstance(adapter, LocalFilesystemStorageAdapter)


def test_build_storage_adapter_uses_s3_compatible_backend_when_seaweedfs_selected() -> None:
    settings = Settings(
        storage_backend="seaweedfs",
        s3_endpoint_url="http://seaweedfs:8333",
        s3_access_key="test-access",
        s3_secret_key="test-secret",
        s3_bucket="uber-rag-documents",
    )

    adapter = build_storage_adapter(settings)

    assert isinstance(adapter, S3CompatibleStorageAdapter)


class FakeS3Client:
    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.put_object_calls.append(kwargs)


def test_s3_compatible_storage_adapter_put_object_forwards_bucket_key_body_and_content_type() -> None:
    fake_client = FakeS3Client()
    adapter = S3CompatibleStorageAdapter(
        endpoint_url="http://seaweedfs:8333",
        access_key="test-access",
        secret_key="test-secret",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=fake_client,
    )

    adapter.put_object(
        object_key="documents/tenant/sample.txt",
        content=b"hello world",
        content_type="text/plain",
    )

    assert fake_client.put_object_calls == [
        {
            "Bucket": "uber-rag-documents",
            "Key": "documents/tenant/sample.txt",
            "Body": b"hello world",
            "ContentType": "text/plain",
        }
    ]


def test_local_filesystem_storage_adapter_materialize_for_read_returns_existing_path(tmp_path: Path) -> None:
    source_path = tmp_path / "documents" / "tenant-1" / "sample.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("hello world")

    adapter = LocalFilesystemStorageAdapter(tmp_path)
    materialized = adapter.materialize_for_read(object_key="documents/tenant-1/sample.txt")

    assert materialized.local_path == source_path
    assert materialized.local_path.read_text() == "hello world"
    assert materialized.cleanup is None


def test_local_filesystem_storage_adapter_materialize_for_read_raises_when_file_missing(tmp_path: Path) -> None:
    adapter = LocalFilesystemStorageAdapter(tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        adapter.materialize_for_read(object_key="documents/missing.txt")

    assert "could not find object" in str(exc_info.value)
    assert "documents/missing.txt" in str(exc_info.value)


def test_s3_compatible_storage_adapter_materialize_for_read_downloads_temp_file(tmp_path: Path) -> None:
    class FakeClient:
        def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
            Path(Filename).write_bytes(b"seaweedfs payload")

    adapter = S3CompatibleStorageAdapter(
        endpoint_url="http://seaweedfs:8333",
        access_key="test-access",
        secret_key="test-secret",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=FakeClient(),
    )

    materialized = adapter.materialize_for_read(object_key="documents/tenant-1/sample.pdf")

    assert materialized.local_path.exists()
    assert materialized.local_path.read_bytes() == b"seaweedfs payload"
    assert materialized.cleanup is not None
    materialized.cleanup()
    assert not materialized.local_path.exists()


def test_s3_compatible_storage_adapter_materialize_for_read_cleans_up_temp_file_on_download_failure() -> None:
    class FailingClient:
        def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
            raise RuntimeError("network timeout")

    adapter = S3CompatibleStorageAdapter(
        endpoint_url="http://seaweedfs:8333",
        access_key="test-access",
        secret_key="test-secret",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=FailingClient(),
    )

    with pytest.raises(RuntimeError, match="network timeout"):
        adapter.materialize_for_read(object_key="documents/tenant-1/missing.pdf")
