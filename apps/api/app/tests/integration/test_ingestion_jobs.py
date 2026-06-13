from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.core.config import Settings, get_settings
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app
from app.repositories.ingestion import ensure_ingestion_stages


class StorageStub:
    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        return None

    def put_object_stream(self, *, object_key: str, fp, content_type: str, content_length: int) -> None:
        fp.read()  # consume the stream; discard bytes


@pytest.fixture(autouse=True)
def reset_global_app_state() -> Generator[None, None, None]:
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    app.state.settings = Settings(parser_backend="")

    for attr in ("document_storage", "dispatcher", "db_engine"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)

    yield

    app.dependency_overrides.clear()
    get_settings.cache_clear()
    app.state.settings = Settings(parser_backend="")

    for attr in ("document_storage", "dispatcher", "db_engine"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture()
def auth_context() -> RequestContext:
    return RequestContext(
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        group_ids=[],
        roles=["editor"],
        scopes=["documents:write", "documents:read"],
    )


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture()
def client(auth_context: RequestContext):
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'ingestion.db'}"
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
        app.state.document_storage = StorageStub()

        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()


def test_list_ingestion_runs_returns_runs_for_current_tenant(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    response = client.get("/api/v1/ingestion/jobs", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["document_id"] == upload.json()["id"]

    compatibility_response = client.get("/api/v1/ingestion/runs", headers=auth_headers)
    assert compatibility_response.status_code == 200
    assert compatibility_response.json() == payload

    with session_factory() as session:
        audit_event = session.scalar(select(AuditEvent).where(AuditEvent.action == "ingestion.run.list"))

        assert audit_event is not None
        assert audit_event.details["run_count"] == 1
        assert audit_event.details["filters_applied"] == ["acl"]


def test_get_ingestion_job_returns_status_payload(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    response = client.get(
        f"/api/v1/ingestion/jobs/{upload.json()['ingestion_run_id']}",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == upload.json()["ingestion_run_id"]
    assert response.json()["workflow_backend"] == "in_process"

    with session_factory() as session:
        audit_event = session.scalar(select(AuditEvent).where(AuditEvent.action == "ingestion.job.get"))

        assert audit_event is not None
        assert audit_event.details["job_id"] == upload.json()["ingestion_run_id"]
        assert audit_event.details["document_id"] == upload.json()["id"]


def test_upload_book_profile_persists_and_is_visible_in_jobs_api(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """F2: the document profile chosen at upload is snapshotted on the run and
    surfaced in the upload response, the jobs list, and the job detail."""
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("textbook.txt", b"hello world", "text/plain")},
        data={"title": "Textbook", "source_type": "loose_document", "profile": "book"},
    )

    assert upload.status_code == 201
    assert upload.json()["profile"] == "book"

    run_id = upload.json()["ingestion_run_id"]

    listed = client.get("/api/v1/ingestion/jobs", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["profile"] == "book"

    detail = client.get(f"/api/v1/ingestion/jobs/{run_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["profile"] == "book"

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == UUID(run_id)))
        assert run is not None
        assert run.profile == "book"


def test_upload_defaults_to_loose_profile(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Omitting profile falls back to loose, preserving prior default behaviour."""
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        data={"title": "Notes", "source_type": "loose_document"},
    )

    assert upload.status_code == 201
    assert upload.json()["profile"] == "loose"

    detail = client.get(
        f"/api/v1/ingestion/jobs/{upload.json()['ingestion_run_id']}",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["profile"] == "loose"


def test_retry_ingestion_job_redispatches_failed_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "failed"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["id"] == str(run_id)
    assert response.json()["status"] in {"queued", "running", "completed"}


def test_retry_ingestion_job_writes_success_audit_event(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "failed"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 200

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id == run_id
    assert audit_event.details["job_id"] == str(run_id)
    assert audit_event.details["document_id"] == upload.json()["id"]
    assert audit_event.details["previous_status"] == "failed"
    assert audit_event.details["resulting_status"] in {"queued", "running", "completed"}


def test_retry_ingestion_job_rejects_completed_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "completed"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 409
    assert response.json() == {"detail": "Ingestion job cannot be retried from status completed"}


def test_retry_ingestion_job_writes_denied_audit_event_for_missing_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    missing_run_id = uuid4()

    response = client.post(f"/api/v1/ingestion/jobs/{missing_run_id}/retry", headers=auth_headers)

    assert response.status_code == 404

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry.denied")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id is None
    assert audit_event.details == {
        "job_id": str(missing_run_id),
        "reason": "not_found_or_denied",
    }


def test_retry_ingestion_job_writes_conflict_audit_event_for_completed_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "completed"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 409

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry.conflict")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id == run_id
    assert audit_event.details == {
        "job_id": str(run_id),
        "document_id": upload.json()["id"],
        "current_status": "completed",
        "reason": "non_retryable_status",
    }


def test_retry_ingestion_job_writes_conflict_audit_event_for_running_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "running"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 409
    assert response.json() == {"detail": "Ingestion job cannot be retried from status running"}

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry.conflict")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id == run_id
    assert audit_event.details == {
        "job_id": str(run_id),
        "document_id": upload.json()["id"],
        "current_status": "running",
        "reason": "non_retryable_status",
    }


def test_retry_ingestion_job_resets_failed_and_running_stages(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])
    tenant_id = UUID(upload.json()["tenant_id"])

    ensure_ingestion_stages(
        run_id=run_id,
        tenant_id=tenant_id,
        stage_names=["parse", "persist_artifact", "quality_report"],
    )

    with session_factory() as session:
        stages = session.scalars(
            select(IngestionStage)
            .where(IngestionStage.run_id == run_id)
            .order_by(IngestionStage.created_at.asc())
        ).all()
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        assert len(stages) == 3
        run.status = "failed"
        stages[0].status = "completed"
        stages[1].status = "failed"
        stages[2].status = "running"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 200

    with session_factory() as session:
        refreshed_stages = session.scalars(
            select(IngestionStage)
            .where(IngestionStage.run_id == run_id)
            .order_by(IngestionStage.created_at.asc())
        ).all()

    assert [stage.status for stage in refreshed_stages] == ["completed", "queued", "queued"]


def test_list_ingestion_runs_resolves_group_names_and_keeps_group_separation(
    auth_context: RequestContext,
    auth_headers: dict[str, str],
) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'ingestion-groups.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        group_a_id = uuid4()
        group_b_id = uuid4()
        requester_user_id = UUID(auth_context.user_id)
        owner_user_id = uuid4()

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="Tenant", slug="tenant-groups"))
            session.add_all(
                [
                    User(
                        id=requester_user_id,
                        tenant_id=UUID(auth_context.tenant_id),
                        email="requester@example.com",
                        display_name="Requester",
                        roles=auth_context.roles,
                    ),
                    User(
                        id=owner_user_id,
                        tenant_id=UUID(auth_context.tenant_id),
                        email="owner@example.com",
                        display_name="Owner",
                        roles=["editor"],
                    ),
                ]
            )
            session.add_all(
                [
                    Group(id=group_a_id, tenant_id=UUID(auth_context.tenant_id), name="group-a"),
                    Group(id=group_b_id, tenant_id=UUID(auth_context.tenant_id), name="group-b"),
                ]
            )
            session.add(UserGroup(user_id=requester_user_id, group_id=group_b_id))

            visible_document = Document(
                tenant_id=UUID(auth_context.tenant_id),
                owner_user_id=owner_user_id,
                title="Visible Group B Document",
                source_type="loose_document",
                source_hash="hash-visible",
                file_name="visible.txt",
                file_size_bytes=1,
                object_key="documents/visible.txt",
                ingestion_status="uploaded",
            )
            hidden_document = Document(
                tenant_id=UUID(auth_context.tenant_id),
                owner_user_id=owner_user_id,
                title="Hidden Group A Document",
                source_type="loose_document",
                source_hash="hash-hidden",
                file_name="hidden.txt",
                file_size_bytes=1,
                object_key="documents/hidden.txt",
                ingestion_status="uploaded",
            )
            session.add_all([visible_document, hidden_document])
            session.flush()
            visible_document_id = visible_document.id
            hidden_document_id = hidden_document.id
            visible_source_hash = visible_document.source_hash
            hidden_source_hash = hidden_document.source_hash

            visible_acl = AclGrant(
                document_id=visible_document.id,
                owner_user_id=owner_user_id,
                tenant_id=UUID(auth_context.tenant_id),
                visibility="group",
                sensitivity="internal",
            )
            hidden_acl = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=owner_user_id,
                tenant_id=UUID(auth_context.tenant_id),
                visibility="group",
                sensitivity="internal",
            )
            session.add_all([visible_acl, hidden_acl])
            session.flush()
            session.add_all(
                [
                        AclAllowedUser(acl_grant_id=visible_acl.id, user_id=owner_user_id),
                        AclAllowedUser(acl_grant_id=hidden_acl.id, user_id=owner_user_id),
                    AclAllowedGroup(acl_grant_id=visible_acl.id, group_id=group_b_id),
                    AclAllowedGroup(acl_grant_id=hidden_acl.id, group_id=group_a_id),
                ]
            )
            session.commit()

        app.dependency_overrides[get_request_context] = lambda: auth_context.model_copy(
            update={"group_ids": ["group-b"], "scopes": ["documents:read"]}
        )
        app.state.document_storage = StorageStub()

        try:
            with session_factory() as session:
                session.add_all(
                    [
                        IngestionRun(
                            document_id=visible_document_id,
                            tenant_id=UUID(auth_context.tenant_id),
                            parser_backend="docling",
                            source_hash=visible_source_hash,
                        ),
                        IngestionRun(
                            document_id=hidden_document_id,
                            tenant_id=UUID(auth_context.tenant_id),
                            parser_backend="docling",
                            source_hash=hidden_source_hash,
                        ),
                    ]
                )
                session.commit()

            with TestClient(app) as client:
                response = client.get("/api/v1/ingestion/jobs", headers=auth_headers)

            assert response.status_code == 200
            titles_by_document_id = {}
            session_factory.configure(bind=engine)
            with session_factory() as session:
                for item in response.json()["items"]:
                    document = session.scalar(select(Document).where(Document.id == UUID(item["document_id"])))
                    assert document is not None
                    titles_by_document_id[str(document.id)] = document.title

            assert "Visible Group B Document" in titles_by_document_id.values()
            assert "Hidden Group A Document" not in titles_by_document_id.values()
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()


def test_group_b_user_cannot_fetch_group_a_ingestion_job_detail(
    auth_context: RequestContext,
    auth_headers: dict[str, str],
) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'ingestion-job-detail-acl.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        group_a_id = uuid4()
        group_b_id = uuid4()
        requester_user_id = UUID(auth_context.user_id)
        owner_user_id = uuid4()

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="Tenant", slug="tenant-job-detail-acl"))
            session.add_all(
                [
                    User(
                        id=requester_user_id,
                        tenant_id=UUID(auth_context.tenant_id),
                        email="requester@example.com",
                        display_name="Requester",
                        roles=auth_context.roles,
                    ),
                    User(
                        id=owner_user_id,
                        tenant_id=UUID(auth_context.tenant_id),
                        email="owner@example.com",
                        display_name="Owner",
                        roles=["editor"],
                    ),
                ]
            )
            session.add_all(
                [
                    Group(id=group_a_id, tenant_id=UUID(auth_context.tenant_id), name="group-a"),
                    Group(id=group_b_id, tenant_id=UUID(auth_context.tenant_id), name="group-b"),
                ]
            )
            session.add(UserGroup(user_id=requester_user_id, group_id=group_b_id))

            hidden_document = Document(
                tenant_id=UUID(auth_context.tenant_id),
                owner_user_id=owner_user_id,
                title="Hidden Group A Document",
                source_type="loose_document",
                source_hash="hash-hidden-job-detail",
                file_name="hidden.txt",
                file_size_bytes=1,
                object_key="documents/hidden.txt",
                ingestion_status="uploaded",
            )
            session.add(hidden_document)
            session.flush()

            hidden_acl = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=owner_user_id,
                tenant_id=UUID(auth_context.tenant_id),
                visibility="group",
                sensitivity="internal",
            )
            session.add(hidden_acl)
            session.flush()
            session.add_all(
                [
                    AclAllowedUser(acl_grant_id=hidden_acl.id, user_id=owner_user_id),
                    AclAllowedGroup(acl_grant_id=hidden_acl.id, group_id=group_a_id),
                ]
            )

            hidden_run = IngestionRun(
                document_id=hidden_document.id,
                tenant_id=UUID(auth_context.tenant_id),
                parser_backend="docling",
                source_hash=hidden_document.source_hash,
            )
            session.add(hidden_run)
            session.commit()
            session.refresh(hidden_run)
            hidden_run_id = hidden_run.id

        app.dependency_overrides[get_request_context] = lambda: auth_context.model_copy(
            update={"group_ids": ["group-b"], "scopes": ["documents:read"]}
        )
        app.state.document_storage = StorageStub()

        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/ingestion/jobs/{hidden_run_id}", headers=auth_headers)

            assert response.status_code == 404
            assert response.json() == {"detail": "Ingestion job not found"}

            session_factory.configure(bind=engine)
            with session_factory() as session:
                deny_event = session.scalar(
                    select(AuditEvent).where(AuditEvent.action == "ingestion.job.get.denied")
                )
                assert deny_event is not None
                assert deny_event.details == {
                    "job_id": str(hidden_run_id),
                    "reason": "not_found_or_denied",
                }
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()


def test_group_b_user_cannot_retry_group_a_ingestion_job(
    auth_context: RequestContext,
    auth_headers: dict[str, str],
) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'ingestion-job-retry-acl.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        group_a_id = uuid4()
        group_b_id = uuid4()
        requester_user_id = UUID(auth_context.user_id)
        owner_user_id = uuid4()

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="Tenant", slug="tenant-job-retry-acl"))
            session.add_all(
                [
                    User(
                        id=requester_user_id,
                        tenant_id=UUID(auth_context.tenant_id),
                        email="requester@example.com",
                        display_name="Requester",
                        roles=auth_context.roles,
                    ),
                    User(
                        id=owner_user_id,
                        tenant_id=UUID(auth_context.tenant_id),
                        email="owner@example.com",
                        display_name="Owner",
                        roles=["editor"],
                    ),
                ]
            )
            session.add_all(
                [
                    Group(id=group_a_id, tenant_id=UUID(auth_context.tenant_id), name="group-a"),
                    Group(id=group_b_id, tenant_id=UUID(auth_context.tenant_id), name="group-b"),
                ]
            )
            session.add(UserGroup(user_id=requester_user_id, group_id=group_b_id))

            hidden_document = Document(
                tenant_id=UUID(auth_context.tenant_id),
                owner_user_id=owner_user_id,
                title="Hidden Group A Document",
                source_type="loose_document",
                source_hash="hash-hidden-job-retry",
                file_name="hidden.txt",
                file_size_bytes=1,
                object_key="documents/hidden.txt",
                ingestion_status="uploaded",
            )
            session.add(hidden_document)
            session.flush()

            hidden_acl = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=owner_user_id,
                tenant_id=UUID(auth_context.tenant_id),
                visibility="group",
                sensitivity="internal",
            )
            session.add(hidden_acl)
            session.flush()
            session.add_all(
                [
                    AclAllowedUser(acl_grant_id=hidden_acl.id, user_id=owner_user_id),
                    AclAllowedGroup(acl_grant_id=hidden_acl.id, group_id=group_a_id),
                ]
            )

            hidden_run = IngestionRun(
                document_id=hidden_document.id,
                tenant_id=UUID(auth_context.tenant_id),
                parser_backend="docling",
                source_hash=hidden_document.source_hash,
            )
            session.add(hidden_run)
            session.commit()
            session.refresh(hidden_run)
            hidden_run_id = hidden_run.id

        app.dependency_overrides[get_request_context] = lambda: auth_context.model_copy(
            update={"group_ids": ["group-b"], "scopes": ["documents:write"]}
        )
        app.state.document_storage = StorageStub()

        try:
            with TestClient(app) as client:
                response = client.post(f"/api/v1/ingestion/jobs/{hidden_run_id}/retry", headers=auth_headers)

            assert response.status_code == 404
            assert response.json() == {"detail": "Ingestion job not found"}

            session_factory.configure(bind=engine)
            with session_factory() as session:
                deny_event = session.scalar(
                    select(AuditEvent)
                    .where(AuditEvent.action == "ingestion.job.retry.denied")
                    .order_by(AuditEvent.timestamp.desc())
                )
                assert deny_event is not None
                assert deny_event.resource_id is None
                assert deny_event.details == {
                    "job_id": str(hidden_run_id),
                    "reason": "not_found_or_denied",
                }
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()
