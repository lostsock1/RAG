from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.services.storage import (
    LocalFilesystemStorageAdapter,
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
