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
from app.db.models.acl import AclAllowedUser, AclGrant
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

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.last_put_object_key = object_key
        self.objects[object_key] = content


class FakeS3Client:
    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.put_object_calls.append(kwargs)


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

        owner_grant = session.scalar(
            select(AclAllowedUser).where(
                AclAllowedUser.acl_grant_id == acl_grant.id,
                AclAllowedUser.user_id == document.owner_user_id,
            )
        )
        assert owner_grant is not None

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
        assert all(run.workflow_backend == "scaffold" for run in runs)

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

    assert len(fake_client.put_object_calls) == 1
    assert fake_client.put_object_calls[0]["Bucket"] == "uber-rag-documents"
    assert fake_client.put_object_calls[0]["Key"] == first_payload["object_key"]
    assert fake_client.put_object_calls[0]["Body"] == b"hello world"
    assert fake_client.put_object_calls[0]["ContentType"] == "text/plain"
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
