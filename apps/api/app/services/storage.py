from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.config import Settings


class StorageAdapter:
    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError

    def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
        raise NotImplementedError


@dataclass(slots=True)
class StoredObject:
    object_key: str
    content_type: str


@dataclass(slots=True)
class MaterializedObject:
    local_path: Path
    cleanup: Callable[[], None] | None = None


class LocalFilesystemStorageAdapter(StorageAdapter):
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        destination = self.root_dir / object_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
        source_path = self.root_dir / object_key
        if not source_path.is_file():
            raise RuntimeError(
                f"Local storage could not find object for key '{object_key}'."
            )
        return MaterializedObject(local_path=source_path, cleanup=None)


class S3CompatibleStorageAdapter(StorageAdapter):
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        client: Any | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - exercised only when S3 writes occur without boto3
            raise RuntimeError(
                "S3-compatible storage requires boto3. Install the API storage dependencies before using the SeaweedFS backend."
            ) from exc

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )
        return self._client

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self._get_client().put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type,
        )

    def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
        with NamedTemporaryFile(delete=False) as tmp_file:
            temp_path = Path(tmp_file.name)

        try:
            self._get_client().download_file(
                Bucket=self.bucket,
                Key=object_key,
                Filename=str(temp_path),
            )
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        def _cleanup() -> None:
            if temp_path.exists():
                temp_path.unlink()

        return MaterializedObject(local_path=temp_path, cleanup=_cleanup)


def build_storage_adapter(settings: Settings) -> StorageAdapter | None:
    if settings.storage_backend == "local" and settings.local_storage_dir:
        return LocalFilesystemStorageAdapter(Path(settings.local_storage_dir))

    if (
        settings.storage_backend == "seaweedfs"
        and settings.s3_endpoint_url
        and settings.s3_access_key
        and settings.s3_secret_key
    ):
        return S3CompatibleStorageAdapter(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )

    return None


def get_storage_adapter(request: Request) -> StorageAdapter:
    storage = getattr(request.app.state, "document_storage", None)
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Document storage is not configured. Set LOCAL_STORAGE_DIR for local development or "
                "configure an S3-compatible storage adapter and try again."
            ),
        )

    return storage
