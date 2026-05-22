from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Iterator
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.base import session_factory
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import create_app


def _request_context() -> RequestContext:
    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        group_ids=[],
        roles=["editor"],
        scopes=["documents:read"],
    )


def _make_app(*, settings: Settings):
    app = create_app(settings)
    app.dependency_overrides[get_request_context] = _request_context
    return app


def test_citations_resolve_returns_only_matched_citation_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.citations.get_source_slice_by_chunk_id",
        lambda **kwargs: {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "document_title": "Doc A",
            "items": [
                {
                    "chunk_id": "chunk-1",
                    "page_start": 1,
                    "page_end": 2,
                    "heading_path": ["Chapter 1"],
                    "is_focus": True,
                }
            ],
        }
        if kwargs["chunk_id"] == "chunk-1"
        else None,
    )
    monkeypatch.setattr("app.api.routes.citations.write_audit_event", lambda **kwargs: None)

    app = _make_app(settings=Settings(llm_backend="stub", parser_backend=""))

    with TestClient(app) as client:
        response = client.post("/api/v1/citations/resolve", json={"citations": ["chunk-1", "missing"]})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "citation_id": "chunk-1",
                "document_id": "doc-1",
                "document_title": "Doc A",
                "chunk_id": "chunk-1",
                "source_viewer_url": "/api/v1/search/sources/chunk-1",
                "page_start": 1,
                "page_end": 2,
                "heading_path": ["Chapter 1"],
            }
        ]
    }


def test_citations_resolve_returns_503_when_source_lookup_unconfigured(monkeypatch) -> None:
    def _raise_runtime_error(**kwargs):
        raise RuntimeError("session_factory has no database bind")

    monkeypatch.setattr("app.api.routes.citations.get_source_slice_by_chunk_id", _raise_runtime_error)
    app = _make_app(settings=Settings(llm_backend="stub", parser_backend=""))

    with TestClient(app) as client:
        response = client.post("/api/v1/citations/resolve", json={"citations": ["chunk-1"]})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Citation resolution is not configured yet. Configure search source lookup before resolving citations."
    )


def test_citations_resolve_rejects_empty_citation_list() -> None:
    app = _make_app(settings=Settings(llm_backend="stub", parser_backend=""))

    with TestClient(app) as client:
        response = client.post("/api/v1/citations/resolve", json={"citations": []})

    assert response.status_code == 422


@pytest.fixture()
def seeded_citation_documents() -> Iterator[dict[str, str]]:
    tenant_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()
    visible_chunk_id = uuid4()
    hidden_chunk_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'citations-route.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-citations'))
            session.add_all(
                [
                    User(id=owner_a_id, tenant_id=tenant_id, email='owner-a@example.com', display_name='Owner A', roles=['editor']),
                    User(id=user_b_id, tenant_id=tenant_id, email='user-b@example.com', display_name='User B', roles=['editor']),
                ]
            )
            session.add_all(
                [
                    Group(id=group_a_id, tenant_id=tenant_id, name='group-a'),
                    Group(id=group_b_id, tenant_id=tenant_id, name='group-b'),
                ]
            )
            session.add_all(
                [
                    UserGroup(user_id=owner_a_id, group_id=group_a_id),
                    UserGroup(user_id=user_b_id, group_id=group_b_id),
                ]
            )

            visible_document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_b_id,
                title='Visible Citation Source',
                source_type='loose_document',
                source_hash='hash-visible',
                file_name='visible.txt',
                file_size_bytes=1,
                object_key='documents/visible.txt',
                ingestion_status='completed',
            )
            hidden_document = Document(
                tenant_id=tenant_id,
                owner_user_id=owner_a_id,
                title='Hidden Citation Source',
                source_type='loose_document',
                source_hash='hash-hidden',
                file_name='hidden.txt',
                file_size_bytes=1,
                object_key='documents/hidden.txt',
                ingestion_status='completed',
            )
            session.add_all([visible_document, hidden_document])
            session.flush()

            visible_acl = AclGrant(
                document_id=visible_document.id,
                owner_user_id=visible_document.owner_user_id,
                tenant_id=visible_document.tenant_id,
                visibility='group',
                sensitivity='internal',
            )
            hidden_acl = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=hidden_document.owner_user_id,
                tenant_id=hidden_document.tenant_id,
                visibility='group',
                sensitivity='internal',
            )
            session.add_all([visible_acl, hidden_acl])
            session.flush()
            session.add_all(
                [
                    AclAllowedUser(acl_grant_id=visible_acl.id, user_id=visible_document.owner_user_id),
                    AclAllowedUser(acl_grant_id=hidden_acl.id, user_id=hidden_document.owner_user_id),
                    AclAllowedGroup(acl_grant_id=visible_acl.id, group_id=group_b_id),
                    AclAllowedGroup(acl_grant_id=hidden_acl.id, group_id=group_a_id),
                ]
            )

            session.add_all(
                [
                    Chunk(
                        id=visible_chunk_id,
                        document_id=visible_document.id,
                        unit_type='paragraph',
                        heading_path=['Visible'],
                        page_start=1,
                        page_end=1,
                        text='Visible citation chunk',
                        parent_id=None,
                        chunk_index=0,
                    ),
                    Chunk(
                        id=hidden_chunk_id,
                        document_id=hidden_document.id,
                        unit_type='paragraph',
                        heading_path=['Hidden'],
                        page_start=2,
                        page_end=2,
                        text='Hidden citation chunk',
                        parent_id=None,
                        chunk_index=0,
                    ),
                ]
            )
            session.commit()

            visible_document_id = str(visible_document.id)

        try:
            yield {
                'database_url': database_url,
                'tenant_id': str(tenant_id),
                'user_b_id': str(user_b_id),
                'group_b_id': str(group_b_id),
                'visible_chunk_id': str(visible_chunk_id),
                'hidden_chunk_id': str(hidden_chunk_id),
                'visible_document_id': visible_document_id,
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def test_citations_resolve_omits_hidden_chunks_for_other_groups(seeded_citation_documents: dict[str, str]) -> None:
    app = create_app(Settings(database_url=seeded_citation_documents['database_url'], llm_backend='stub', parser_backend=''))
    app.dependency_overrides[get_request_context] = lambda: RequestContext(
        tenant_id=seeded_citation_documents['tenant_id'],
        user_id=seeded_citation_documents['user_b_id'],
        group_ids=[seeded_citation_documents['group_b_id']],
        roles=['editor'],
        scopes=['documents:read'],
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/citations/resolve",
                json={
                    "citations": [
                        seeded_citation_documents['visible_chunk_id'],
                        seeded_citation_documents['hidden_chunk_id'],
                    ]
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "citation_id": seeded_citation_documents['visible_chunk_id'],
            "document_id": seeded_citation_documents['visible_document_id'],
            "document_title": 'Visible Citation Source',
            "chunk_id": seeded_citation_documents['visible_chunk_id'],
            "source_viewer_url": f"/api/v1/search/sources/{seeded_citation_documents['visible_chunk_id']}",
            "page_start": 1,
            "page_end": 1,
            "heading_path": ['Visible'],
        }
    ]
