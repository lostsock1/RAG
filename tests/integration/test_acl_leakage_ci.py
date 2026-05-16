from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))

from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.models.acl import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app


def test_acl_group_separation_blocks_document_list_leakage() -> None:
    tenant_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'acl-leakage.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-acl-leakage"))
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

            hidden_document = Document(
                tenant_id=tenant_id,
                owner_user_id=owner_a_id,
                title="Group A Secret",
                source_type="loose_document",
                source_hash="hash-a-secret",
                file_name="group-a.txt",
                file_size_bytes=1,
                object_key="documents/group-a.txt",
                ingestion_status="uploaded",
            )
            visible_document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_b_id,
                title="Group B Visible",
                source_type="loose_document",
                source_hash="hash-b-visible",
                file_name="group-b.txt",
                file_size_bytes=1,
                object_key="documents/group-b.txt",
                ingestion_status="uploaded",
            )
            session.add_all([hidden_document, visible_document])
            session.flush()

            hidden_grant = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=owner_a_id,
                tenant_id=tenant_id,
                visibility="group",
                sensitivity="internal",
            )
            visible_grant = AclGrant(
                document_id=visible_document.id,
                owner_user_id=user_b_id,
                tenant_id=tenant_id,
                visibility="group",
                sensitivity="internal",
            )
            session.add_all([hidden_grant, visible_grant])
            session.flush()

            session.add_all(
                [
                    AclAllowedUser(acl_grant_id=hidden_grant.id, user_id=owner_a_id),
                    AclAllowedGroup(acl_grant_id=hidden_grant.id, group_id=group_a_id),
                    AclAllowedUser(acl_grant_id=visible_grant.id, user_id=user_b_id),
                    AclAllowedGroup(acl_grant_id=visible_grant.id, group_id=group_b_id),
                ]
            )
            session.commit()

        app.dependency_overrides[get_request_context] = lambda: RequestContext(
            tenant_id=str(tenant_id),
            user_id=str(user_b_id),
            group_ids=[str(group_b_id)],
            roles=["editor"],
            scopes=["documents:read"],
        )

        try:
            client = TestClient(app)
            response = client.get("/api/v1/documents")
            assert response.status_code == 200
            titles = [item["title"] for item in response.json()["items"]]
            assert titles == ["Group B Visible"]
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()
