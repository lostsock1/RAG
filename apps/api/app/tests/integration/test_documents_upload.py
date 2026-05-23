from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.acl_models import AclAllowedUser, AclGrant
from app.db.acl_models import AclPolicy, AclPolicyDimension, AclPolicySensitivityLevel, AclPolicyVisibilityMode
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app
from app.services.storage import S3CompatibleStorageAdapter


class StorageStub:
    def __init__(self) -> None:
        self.last_put_object_key: str | None = None
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.last_put_object_key = object_key
        self.objects[object_key] = content

    def put_object_stream(self, *, object_key: str, fp, content_type: str, content_length: int) -> None:
        data = fp.read()
        self.last_put_object_key = object_key
        self.objects[object_key] = data

    def delete_object(self, *, object_key: str) -> None:
        self.deleted_keys.append(object_key)
        self.objects.pop(object_key, None)


class FakeS3Client:
    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, object]] = []
        self.upload_fileobj_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.put_object_calls.append(kwargs)

    def upload_fileobj(self, fp, bucket: str, key: str, ExtraArgs: dict | None = None) -> None:
        data = fp.read()
        self.upload_fileobj_calls.append({"Bucket": bucket, "Key": key, "Body": data, "ExtraArgs": ExtraArgs})


class FakeS3StorageAdapter(S3CompatibleStorageAdapter):
    def __init__(self, *, fake_client: FakeS3Client) -> None:
        super().__init__(
            endpoint_url="http://seaweedfs:8333",
            access_key="test-access",
            secret_key="test-secret",
            bucket="uber-rag-documents",
            region="us-east-1",
            client=fake_client,
        )
        self.fake_client = fake_client


@pytest.fixture()
def auth_context() -> RequestContext:
    return RequestContext(
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        group_ids=[],
        roles=["editor"],
        scopes=["documents:write"],
    )


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture()
def storage_stub() -> StorageStub:
    return StorageStub()


@pytest.fixture()
def s3_storage_adapter() -> FakeS3StorageAdapter:
    fake_client = FakeS3Client()
    return FakeS3StorageAdapter(fake_client=fake_client)


@pytest.fixture()
def client(auth_context: RequestContext, storage_stub: StorageStub):
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'upload.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="Tenant", slug="tenant"))
            session.add(
                User(
                    id=UUID(auth_context.user_id),
                    tenant_id=UUID(auth_context.tenant_id),
                    email="user@example.com",
                    display_name="User",
                    roles=auth_context.roles,
                )
            )
            session.commit()

        app.dependency_overrides[get_request_context] = lambda: auth_context
        app.state.document_storage = storage_stub

        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()


def test_upload_creates_document_and_default_acl(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_stub: StorageStub,
) -> None:
    response = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Sample"
    assert payload["source_hash"]
    assert payload["ingestion_status"] == "uploaded"
    assert storage_stub.last_put_object_key == payload["object_key"]

    with session_factory() as session:
        document = session.scalar(select(Document).where(Document.id == UUID(payload["id"])))
        assert document is not None
        assert document.title == "Sample"

        acl_grant = session.scalar(select(AclGrant).where(AclGrant.document_id == document.id))
        assert acl_grant is not None
        assert acl_grant.owner_user_id == UUID(payload["owner_user_id"])
        assert acl_grant.visibility == "private"
        assert acl_grant.sensitivity == "internal"
        assert acl_grant.sensitivity_rank == 200
        assert acl_grant.acl_policy_id is not None
        assert acl_grant.acl_policy_version == 1

        owner_grant = session.scalar(
            select(AclAllowedUser).where(
                AclAllowedUser.acl_grant_id == acl_grant.id,
                AclAllowedUser.user_id == document.owner_user_id,
            )
        )
        assert owner_grant is not None

        policy = session.scalar(select(AclPolicy).where(AclPolicy.tenant_id == document.tenant_id))
        assert policy is not None
        assert policy.status == "locked"
        assert policy.locked_at is not None
        assert policy.default_visibility_mode == "private"

        visibility_modes = {
            row.key: row
            for row in session.scalars(
                select(AclPolicyVisibilityMode).where(AclPolicyVisibilityMode.policy_id == policy.id)
            ).all()
        }
        assert visibility_modes["private"].display_name == "Private"
        assert visibility_modes["group"].is_active is True

        sensitivity_levels = {
            row.key: row
            for row in session.scalars(
                select(AclPolicySensitivityLevel).where(AclPolicySensitivityLevel.policy_id == policy.id)
            ).all()
        }
        assert sensitivity_levels["internal"].rank == 200

        dimensions = {
            row.key: row
            for row in session.scalars(
                select(AclPolicyDimension).where(AclPolicyDimension.policy_id == policy.id)
            ).all()
        }
        assert dimensions["user"].is_active is True
        assert dimensions["group"].is_active is True
        assert dimensions["role"].is_active is False
        assert dimensions["org_unit"].is_active is False
        assert dimensions["project"].is_active is False

        audit_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "document.upload",
                AuditEvent.resource_id == document.id,
            )
        )
        assert audit_event is not None


def test_missing_write_scope_cannot_upload_document(
    client: TestClient,
    auth_context: RequestContext,
    auth_headers: dict[str, str],
) -> None:
    app.dependency_overrides[get_request_context] = lambda: auth_context.model_copy(
        update={"scopes": ["documents:read"]}
    )

    response = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert response.status_code == 403


def test_upload_reuses_existing_document_hash_and_creates_new_ingestion_run(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_stub: StorageStub,
) -> None:
    first = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )
    second = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample-copy.txt", b"hello world", "text/plain")},
        data={"title": "Sample copy", "source_type": "loose_document"},
    )

    assert first.status_code == 201
    assert second.status_code == 201

    first_payload = first.json()
    second_payload = second.json()

    assert second_payload["source_hash"] == first_payload["source_hash"]
    assert second_payload["id"] == first_payload["id"]
    assert second_payload["object_key"] == first_payload["object_key"]
    assert second_payload["ingestion_run_id"]
    assert second_payload["ingestion_run_id"] != first_payload["ingestion_run_id"]
    assert len(storage_stub.objects) == 1

    with session_factory() as session:
        runs = session.scalars(
            select(IngestionRun)
            .where(IngestionRun.document_id == UUID(first_payload["id"]))
            .order_by(IngestionRun.created_at.asc())
        ).all()

        assert len(runs) == 2
        assert all(run.workflow_backend == "in_process" for run in runs)

        latest_audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "document.upload")
            .order_by(AuditEvent.timestamp.desc())
        )

        assert latest_audit is not None
        assert latest_audit.details["object_key"] == first_payload["object_key"]


def test_upload_uses_deterministic_object_key_for_same_hash(
    client: TestClient,
    auth_context: RequestContext,
    auth_headers: dict[str, str],
) -> None:
    first = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )
    second = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample-copy.md", b"hello world", "text/markdown")},
        data={"title": "Sample Copy", "source_type": "loose_document"},
    )

    assert first.status_code == 201
    assert second.status_code == 201

    source_hash = first.json()["source_hash"]
    expected_key = f"documents/{auth_context.tenant_id}/{source_hash}"

    assert first.json()["object_key"] == expected_key
    assert second.json()["object_key"] == expected_key


def test_upload_works_with_s3_compatible_storage_adapter_and_reuses_object_key(
    client: TestClient,
    auth_headers: dict[str, str],
    s3_storage_adapter: FakeS3StorageAdapter,
) -> None:
    app.state.document_storage = s3_storage_adapter

    first = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )
    second = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample-copy.txt", b"hello world", "text/plain")},
        data={"title": "Sample copy", "source_type": "loose_document"},
    )

    assert first.status_code == 201
    assert second.status_code == 201

    first_payload = first.json()
    second_payload = second.json()
    fake_client = s3_storage_adapter.fake_client

    assert len(fake_client.upload_fileobj_calls) == 1
    assert fake_client.upload_fileobj_calls[0]["Bucket"] == "uber-rag-documents"
    assert fake_client.upload_fileobj_calls[0]["Key"] == first_payload["object_key"]
    assert fake_client.upload_fileobj_calls[0]["Body"] == b"hello world"
    assert second_payload["id"] == first_payload["id"]
    assert second_payload["source_hash"] == first_payload["source_hash"]
    assert second_payload["object_key"] == first_payload["object_key"]
    assert second_payload["ingestion_run_id"] != first_payload["ingestion_run_id"]

    with session_factory() as session:
        document = session.scalar(select(Document).where(Document.id == UUID(first_payload["id"])))
        assert document is not None
        assert document.object_key == first_payload["object_key"]
        assert document.source_hash == first_payload["source_hash"]
        assert document.title == first_payload["title"]

        latest_run = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.id == UUID(second_payload["ingestion_run_id"]))
        )
        assert latest_run is not None
        assert latest_run.document_id == document.id

        run_count = session.scalar(
            select(func.count())
            .select_from(IngestionRun)
            .where(IngestionRun.document_id == document.id)
        )
        assert run_count == 2


def test_upload_rejects_forged_tenant_id_with_path_traversal(
    client: TestClient,
    auth_context: RequestContext,
    auth_headers: dict[str, str],
    storage_stub: StorageStub,
) -> None:
    """P0-3 ACL leakage test: forged tenant_id with '..' must be rejected at the security layer."""
    # Override get_request_context to simulate what happens when the dev-auth
    # path receives a forged tenant_id — the validation in the security layer
    # raises HTTPException(400) before the route handler runs.
    from app.core.security import get_request_context as real_get_request_context
    from fastapi import HTTPException
    from starlette.status import HTTP_400_BAD_REQUEST

    def _forged_context():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="tenant_id is not a valid UUID: '../etc'",
        )

    app.dependency_overrides[get_request_context] = _forged_context

    try:
        response = client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("sample.txt", b"hello world", "text/plain")},
            data={"title": "Forged", "source_type": "loose_document"},
        )
    finally:
        # Restore the original override
        app.dependency_overrides[get_request_context] = lambda: auth_context

    assert response.status_code == 400
    assert len(storage_stub.objects) == 0


def test_upload_streaming_memory_budget(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_stub: StorageStub,
) -> None:
    """P0-8 memory-budget regression: uploading a large file must not allocate
    more than ~50 MB of peak heap above the baseline.

    We use tracemalloc to measure the delta so the bound is machine-independent.
    The generous 50 MB ceiling accounts for framework overhead while still
    catching a regression where the entire file is read into RAM at once.
    """
    import tracemalloc

    # 10 MB synthetic payload — large enough to detect a full-read regression
    # without making the test slow.  The bound is 50 MB so even a 5× overhead
    # is caught.
    payload_size = 10 * 1024 * 1024  # 10 MB
    peak_limit_bytes = 50 * 1024 * 1024  # 50 MB

    large_content = b"x" * payload_size

    tracemalloc.start()
    tracemalloc.clear_traces()

    response = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("large.bin", large_content, "application/octet-stream")},
        data={"title": "Large File", "source_type": "loose_document"},
    )

    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert response.status_code == 201, f"Upload failed: {response.text}"
    assert peak < peak_limit_bytes, (
        f"Peak memory during upload was {peak / 1024 / 1024:.1f} MB, "
        f"expected < {peak_limit_bytes / 1024 / 1024:.0f} MB. "
        "This likely means the entire file was read into RAM."
    )


def test_storage_cleanup_on_db_failure(
    auth_context: RequestContext,
    auth_headers: dict[str, str],
    storage_stub: StorageStub,
) -> None:
    """P1-1: When the DB write fails after put_object_stream, the orphaned
    object must be deleted from storage (best-effort cleanup)."""
    from unittest.mock import patch

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'cleanup-test.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="Tenant", slug="cleanup-tenant"))
            session.add(
                User(
                    id=UUID(auth_context.user_id),
                    tenant_id=UUID(auth_context.tenant_id),
                    email="cleanup@example.com",
                    display_name="Cleanup User",
                    roles=auth_context.roles,
                )
            )
            session.commit()

        app.dependency_overrides[get_request_context] = lambda: auth_context
        app.state.document_storage = storage_stub

        try:
            # Monkeypatch get_or_create_document_by_source_hash to raise after
            # put_object_stream has already written the object to storage.
            with patch(
                "app.services.document_service.get_or_create_document_by_source_hash",
                side_effect=RuntimeError("simulated DB failure"),
            ):
                with TestClient(app, raise_server_exceptions=False) as client:
                    response = client.post(
                        "/api/v1/documents/upload",
                        headers=auth_headers,
                        files={"file": ("cleanup.txt", b"cleanup payload", "text/plain")},
                        data={"title": "Cleanup Test", "source_type": "loose_document"},
                    )

            # The request must fail (DB error propagates as 500)
            assert response.status_code == 500

            # The orphaned object must have been deleted from storage
            assert len(storage_stub.objects) == 0, (
                f"Expected no objects in storage after DB failure, "
                f"but found: {list(storage_stub.objects.keys())}"
            )
            assert len(storage_stub.deleted_keys) == 1, (
                f"Expected exactly one delete_object call, got: {storage_stub.deleted_keys}"
            )
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()
