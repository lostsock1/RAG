from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app


@pytest.fixture()
def seeded_documents() -> dict[str, str]:
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()
    other_tenant_user_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'documents-list-acl.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add_all(
                [
                    Tenant(id=tenant_id, name="Tenant One", slug="tenant-one-list"),
                    Tenant(id=other_tenant_id, name="Tenant Two", slug="tenant-two-list"),
                ]
            )
            session.add_all(
                [
                    User(
                        id=owner_a_id,
                        tenant_id=tenant_id,
                        email="owner-a@example.com",
                        display_name="Owner A",
                        roles=["editor"],
                    ),
                    User(
                        id=user_b_id,
                        tenant_id=tenant_id,
                        email="user-b@example.com",
                        display_name="User B",
                        roles=["editor"],
                    ),
                    User(
                        id=other_tenant_user_id,
                        tenant_id=other_tenant_id,
                        email="other-tenant@example.com",
                        display_name="Other Tenant User",
                        roles=["editor"],
                    ),
                ]
            )
            session.add_all(
                [
                    Group(id=group_a_id, tenant_id=tenant_id, name="group-a"),
                    Group(id=group_b_id, tenant_id=tenant_id, name="group-b"),
                ]
            )
            session.add_all(
                [
                    UserGroup(user_id=owner_a_id, group_id=group_a_id),
                    UserGroup(user_id=user_b_id, group_id=group_b_id),
                ]
            )

            documents = [
                (
                    Document(
                        tenant_id=tenant_id,
                        owner_user_id=owner_a_id,
                        title="Group A Secret",
                        source_type="loose_document",
                        source_hash="hash-a",
                        file_name="a.txt",
                        file_size_bytes=1,
                        object_key="documents/a.txt",
                        ingestion_status="uploaded",
                    ),
                    "group",
                    [],
                    [group_a_id],
                ),
                (
                    Document(
                        tenant_id=tenant_id,
                        owner_user_id=user_b_id,
                        title="Group B Visible",
                        source_type="loose_document",
                        source_hash="hash-b",
                        file_name="b.txt",
                        file_size_bytes=1,
                        object_key="documents/b.txt",
                        ingestion_status="uploaded",
                    ),
                    "group",
                    [],
                    [group_b_id],
                ),
                (
                    Document(
                        tenant_id=tenant_id,
                        owner_user_id=owner_a_id,
                        title="Tenant Shared",
                        source_type="loose_document",
                        source_hash="hash-tenant",
                        file_name="tenant.txt",
                        file_size_bytes=1,
                        object_key="documents/tenant.txt",
                        ingestion_status="uploaded",
                    ),
                    "tenant",
                    [],
                    [],
                ),
                (
                    Document(
                        tenant_id=tenant_id,
                        owner_user_id=owner_a_id,
                        title="Tenant Authenticated Public",
                        source_type="loose_document",
                        source_hash="hash-public",
                        file_name="public.txt",
                        file_size_bytes=1,
                        object_key="documents/public.txt",
                        ingestion_status="uploaded",
                    ),
                    "public",
                    [],
                    [],
                ),
                (
                    Document(
                        tenant_id=tenant_id,
                        owner_user_id=owner_a_id,
                        title="Explicit User Visible",
                        source_type="loose_document",
                        source_hash="hash-user",
                        file_name="user.txt",
                        file_size_bytes=1,
                        object_key="documents/user.txt",
                        ingestion_status="uploaded",
                    ),
                    "private",
                    [user_b_id],
                    [],
                ),
                (
                    Document(
                        tenant_id=tenant_id,
                        owner_user_id=owner_a_id,
                        title="Owner Only Private",
                        source_type="loose_document",
                        source_hash="hash-private",
                        file_name="private.txt",
                        file_size_bytes=1,
                        object_key="documents/private.txt",
                        ingestion_status="uploaded",
                    ),
                    "private",
                    [],
                    [],
                ),
            ]

            for document, visibility, allowed_users, allowed_groups in documents:
                session.add(document)
                session.flush()
                acl_grant = AclGrant(
                    document_id=document.id,
                    owner_user_id=document.owner_user_id,
                    tenant_id=document.tenant_id,
                    visibility=visibility,
                    sensitivity="internal",
                )
                session.add(acl_grant)
                session.flush()
                session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=document.owner_user_id))
                for allowed_user_id in allowed_users:
                    session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=allowed_user_id))
                for allowed_group_id in allowed_groups:
                    session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=allowed_group_id))

            session.commit()

        try:
            yield {
                "tenant_id": str(tenant_id),
                "other_tenant_id": str(other_tenant_id),
                "owner_a_id": str(owner_a_id),
                "user_b_id": str(user_b_id),
                "other_tenant_user_id": str(other_tenant_user_id),
                "group_a_id": str(group_a_id),
                "group_b_id": str(group_b_id),
            }
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()


def make_client(context: RequestContext) -> TestClient:
    app.dependency_overrides[get_request_context] = lambda: context
    return TestClient(app)


def test_group_b_user_cannot_see_group_a_document(seeded_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_documents["tenant_id"],
            user_id=seeded_documents["user_b_id"],
            group_ids=[seeded_documents["group_b_id"]],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Group A Secret" not in titles
    assert "Group B Visible" in titles
    assert "Tenant Shared" in titles
    assert "Tenant Authenticated Public" in titles
    assert "Explicit User Visible" in titles
    assert "Owner Only Private" not in titles

    with session_factory() as session:
        audit_event = session.scalar(select(AuditEvent).where(AuditEvent.action == "document.list"))
        assert audit_event is not None


def test_owner_can_see_private_document_in_list(seeded_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_documents["tenant_id"],
            user_id=seeded_documents["owner_a_id"],
            group_ids=[seeded_documents["group_a_id"]],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Owner Only Private" in titles
    assert "Group B Visible" not in titles


def test_other_tenant_user_cannot_see_tenant_shared_document(seeded_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_documents["other_tenant_id"],
            user_id=seeded_documents["other_tenant_user_id"],
            group_ids=[],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_public_visibility_remains_tenant_scoped_not_cross_tenant(seeded_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_documents["other_tenant_id"],
            user_id=seeded_documents["other_tenant_user_id"],
            group_ids=[],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    assert "Tenant Authenticated Public" not in [item["title"] for item in response.json()["items"]]


def test_missing_read_scope_cannot_list_documents(seeded_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_documents["tenant_id"],
            user_id=seeded_documents["user_b_id"],
            group_ids=[seeded_documents["group_b_id"]],
            roles=["editor"],
            scopes=[],
        )
    )

    response = client.get("/api/v1/documents")
    assert response.status_code == 403


def test_expired_acl_grant_hides_document_from_list(seeded_documents: dict[str, str]) -> None:
    expired_document = Document(
        tenant_id=UUID(seeded_documents["tenant_id"]),
        owner_user_id=UUID(seeded_documents["owner_a_id"]),
        title="Expired Explicit Grant",
        source_type="loose_document",
        source_hash="hash-expired-user",
        file_name="expired-user.txt",
        file_size_bytes=1,
        object_key="documents/expired-user.txt",
        ingestion_status="uploaded",
    )

    with session_factory() as session:
        session.add(expired_document)
        session.flush()
        acl_grant = AclGrant(
            document_id=expired_document.id,
            owner_user_id=expired_document.owner_user_id,
            tenant_id=expired_document.tenant_id,
            visibility="private",
            sensitivity="internal",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add(acl_grant)
        session.flush()
        session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=expired_document.owner_user_id))
        session.add(
            AclAllowedUser(
                acl_grant_id=acl_grant.id,
                user_id=UUID(seeded_documents["user_b_id"]),
            )
        )
        session.commit()

    client = make_client(
        RequestContext(
            tenant_id=seeded_documents["tenant_id"],
            user_id=seeded_documents["user_b_id"],
            group_ids=[seeded_documents["group_b_id"]],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Expired Explicit Grant" not in titles
