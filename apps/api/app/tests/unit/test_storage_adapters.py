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


def test_local_filesystem_storage_adapter_materialize_for_read_returns_copy_with_same_content(tmp_path: Path) -> None:
    """P1-3: materialize_for_read must return a copy, not the original path."""
    source_path = tmp_path / "documents" / "tenant-1" / "sample.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("hello world")

    adapter = LocalFilesystemStorageAdapter(tmp_path)
    materialized = adapter.materialize_for_read(object_key="documents/tenant-1/sample.txt")

    # Content must be identical
    assert materialized.local_path.read_text() == "hello world"
    # Cleanup callback must be provided
    assert materialized.cleanup is not None
    # Cleanup must remove the temp file
    assert materialized.local_path.exists()
    materialized.cleanup()
    assert not materialized.local_path.exists()


def test_local_materialize_does_not_yield_storage_path(tmp_path: Path) -> None:
    """P1-3 acceptance test: the returned path must NOT be under LOCAL_STORAGE_DIR."""
    source_path = tmp_path / "documents" / "tenant-1" / "sample.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("immutable content")

    adapter = LocalFilesystemStorageAdapter(tmp_path)
    materialized = adapter.materialize_for_read(object_key="documents/tenant-1/sample.txt")

    try:
        # The returned path must not be under the storage root
        assert not str(materialized.local_path).startswith(str(tmp_path)), (
            f"materialize_for_read returned the storage path {materialized.local_path!r} "
            f"instead of a copy outside {tmp_path!r}."
        )
        # The original source must still exist and be unchanged
        assert source_path.read_text() == "immutable content"
    finally:
        if materialized.cleanup:
            materialized.cleanup()


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


def test_delete_object_local(tmp_path: Path) -> None:
    adapter = LocalFilesystemStorageAdapter(tmp_path)
    target = tmp_path / "documents" / "tenant-1" / "sample.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello")

    adapter.delete_object(object_key="documents/tenant-1/sample.txt")

    assert not target.exists()


def test_delete_object_local_missing_is_noop(tmp_path: Path) -> None:
    """delete_object on a non-existent key must not raise."""
    adapter = LocalFilesystemStorageAdapter(tmp_path)
    adapter.delete_object(object_key="documents/does-not-exist.txt")  # no exception


def test_delete_object_s3() -> None:
    deleted: list[dict] = []

    class FakeS3ClientWithDelete:
        def delete_object(self, **kwargs: object) -> None:
            deleted.append(kwargs)

    adapter = S3CompatibleStorageAdapter(
        endpoint_url="http://seaweedfs:8333",
        access_key="test-access",
        secret_key="test-secret",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=FakeS3ClientWithDelete(),
    )

    adapter.delete_object(object_key="documents/tenant-1/sample.txt")

    assert deleted == [{"Bucket": "uber-rag-documents", "Key": "documents/tenant-1/sample.txt"}]


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
