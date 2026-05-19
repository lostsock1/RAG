from __future__ import annotations

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
def seeded_acl_state() -> dict[str, str]:
    tenant_id = uuid4()
    owner_user_id = uuid4()
    admin_user_id = uuid4()
    outsider_user_id = uuid4()
    owner_group_id = uuid4()
    outsider_group_id = uuid4()
    document_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'document-acl.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-acl"))
            session.add_all(
                [
                    User(
                        id=owner_user_id,
                        tenant_id=tenant_id,
                        email="owner@example.com",
                        display_name="Owner",
                        roles=["editor"],
                    ),
                    User(
                        id=admin_user_id,
                        tenant_id=tenant_id,
                        email="admin@example.com",
                        display_name="Admin",
                        roles=["admin"],
                    ),
                    User(
                        id=outsider_user_id,
                        tenant_id=tenant_id,
                        email="outsider@example.com",
                        display_name="Outsider",
                        roles=["editor"],
                    ),
                ]
            )
            session.add_all(
                [
                    Group(id=owner_group_id, tenant_id=tenant_id, name="group-a"),
                    Group(id=outsider_group_id, tenant_id=tenant_id, name="group-b"),
                ]
            )
            session.add_all(
                [
                    UserGroup(user_id=owner_user_id, group_id=owner_group_id),
                    UserGroup(user_id=outsider_user_id, group_id=outsider_group_id),
                ]
            )

            session.add(
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    title="Owner Document",
                    source_type="loose_document",
                    source_hash="hash-owner-document",
                    file_name="owner.txt",
                    file_size_bytes=12,
                    object_key="documents/owner.txt",
                    ingestion_status="uploaded",
                )
            )
            session.add(
                AclGrant(
                    document_id=document_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    visibility="private",
                    sensitivity="internal",
                )
            )
            session.commit()

            acl_grant = session.scalar(select(AclGrant).where(AclGrant.document_id == document_id))
            assert acl_grant is not None
            session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=owner_user_id))
            session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=owner_group_id))
            session.commit()

        try:
            yield {
                "tenant_id": str(tenant_id),
                "owner_user_id": str(owner_user_id),
                "admin_user_id": str(admin_user_id),
                "outsider_user_id": str(outsider_user_id),
                "owner_group_id": str(owner_group_id),
                "outsider_group_id": str(outsider_group_id),
                "document_id": str(document_id),
            }
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()


def make_client(context: RequestContext) -> TestClient:
    app.dependency_overrides[get_request_context] = lambda: context
    return TestClient(app)


def test_owner_can_read_and_update_document_acl(seeded_acl_state: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_state["tenant_id"],
            user_id=seeded_acl_state["owner_user_id"],
            group_ids=[seeded_acl_state["owner_group_id"]],
            roles=["editor"],
            scopes=["documents:read", "documents:write"],
        )
    )

    get_response = client.get(f"/api/v1/documents/{seeded_acl_state['document_id']}/acl")
    assert get_response.status_code == 200
    assert get_response.json()["visibility"] == "private"

    put_response = client.put(
        f"/api/v1/documents/{seeded_acl_state['document_id']}/acl",
        json={
            "visibility": "group",
            "allowed_user_ids": [seeded_acl_state["outsider_user_id"]],
            "allowed_group_ids": [seeded_acl_state["outsider_group_id"]],
            "sensitivity": "internal",
        },
    )
    assert put_response.status_code == 200
    payload = put_response.json()
    assert payload["visibility"] == "group"
    assert seeded_acl_state["outsider_user_id"] in payload["allowed_user_ids"]
    assert seeded_acl_state["outsider_group_id"] in payload["allowed_group_ids"]

    with session_factory() as session:
        acl_grant = session.scalar(
            select(AclGrant).where(AclGrant.document_id == UUID(seeded_acl_state["document_id"]))
        )
        assert acl_grant is not None
        assert acl_grant.visibility == "group"

        audit_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "acl.update",
                AuditEvent.resource_id == UUID(seeded_acl_state["document_id"]),
            )
        )
        assert audit_event is not None


def test_admin_can_read_and_update_document_acl(seeded_acl_state: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_state["tenant_id"],
            user_id=seeded_acl_state["admin_user_id"],
            group_ids=[],
            roles=["admin"],
            scopes=["documents:read", "documents:write"],
        )
    )

    get_response = client.get(f"/api/v1/documents/{seeded_acl_state['document_id']}/acl")
    assert get_response.status_code == 200

    put_response = client.put(
        f"/api/v1/documents/{seeded_acl_state['document_id']}/acl",
        json={
            "visibility": "tenant",
            "allowed_user_ids": [],
            "allowed_group_ids": [],
            "sensitivity": "internal",
        },
    )
    assert put_response.status_code == 200
    assert put_response.json()["visibility"] == "tenant"


def test_non_owner_non_admin_cannot_read_document_acl(seeded_acl_state: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_state["tenant_id"],
            user_id=seeded_acl_state["outsider_user_id"],
            group_ids=[seeded_acl_state["outsider_group_id"]],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.get(f"/api/v1/documents/{seeded_acl_state['document_id']}/acl")
    assert response.status_code == 404


def test_missing_read_scope_cannot_get_document_acl(seeded_acl_state: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_state["tenant_id"],
            user_id=seeded_acl_state["owner_user_id"],
            group_ids=[seeded_acl_state["owner_group_id"]],
            roles=["editor"],
            scopes=[],
        )
    )

    response = client.get(f"/api/v1/documents/{seeded_acl_state['document_id']}/acl")
    assert response.status_code == 403


def test_missing_write_scope_cannot_update_document_acl(seeded_acl_state: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_state["tenant_id"],
            user_id=seeded_acl_state["owner_user_id"],
            group_ids=[seeded_acl_state["owner_group_id"]],
            roles=["editor"],
            scopes=["documents:read"],
        )
    )

    response = client.put(
        f"/api/v1/documents/{seeded_acl_state['document_id']}/acl",
        json={
            "visibility": "group",
            "allowed_user_ids": [],
            "allowed_group_ids": [seeded_acl_state["outsider_group_id"]],
            "sensitivity": "internal",
        },
    )
    assert response.status_code == 403
