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
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import create_app


class _VerifyRetrieverStub:
    """Returns a hit whose text contains the answer sentence."""

    def search(self, query) -> list[dict]:
        return [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "score": 0.9,
                "text": "Alpha evidence proves the answer.",
                "page_start": 1,
                "page_end": 1,
                "heading_path": ["Section 1"],
                "route": "semantic",
            }
        ]


def _request_context() -> RequestContext:
    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        group_ids=[],
        roles=["editor"],
        scopes=["documents:read"],
    )


def _make_app(*, settings: Settings, retriever=None):
    app = create_app(settings)
    app.dependency_overrides[get_request_context] = _request_context
    if retriever is not None:
        app.state.search_retriever = retriever
    return app


def test_answers_verify_returns_supported_when_evidence_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [
            type("DocRow", (), {"id": "doc-1", "title": "Doc A", "source_type": "loose_document"})()
        ],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)

    app = _make_app(
        settings=Settings(llm_backend="stub", parser_backend=""),
        retriever=_VerifyRetrieverStub(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/answers/verify",
            json={
                "question": "What happened?",
                "answer_text": "Alpha evidence proves the answer.",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "supported"
    assert body["supported_sentence_count"] == 1


def test_answers_verify_returns_503_when_retriever_missing() -> None:
    app = _make_app(settings=Settings(llm_backend="stub", parser_backend=""))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/answers/verify",
            json={
                "question": "What happened?",
                "answer_text": "Something.",
                "top_k": 3,
            },
        )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_answers_verify_rejects_blank_question() -> None:
    app = _make_app(settings=Settings(llm_backend="stub", parser_backend=""), retriever=_VerifyRetrieverStub())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/answers/verify",
            json={
                "question": "   ",
                "answer_text": "Alpha evidence proves the answer.",
                "top_k": 3,
            },
        )

    assert response.status_code == 422


class _AclVerifyRetrieverStub:
    def __init__(self, *, hidden_document_id: str) -> None:
        self.hidden_document_id = hidden_document_id

    def search(self, query) -> list[dict]:
        return [
            {
                "document_id": self.hidden_document_id,
                "chunk_id": "chunk-hidden-1",
                "score": 0.9,
                "text": "Hidden evidence that should be filtered out.",
                "page_start": 4,
                "page_end": 4,
                "heading_path": ["Secret"],
                "route": "semantic",
            }
        ]


@pytest.fixture()
def seeded_verify_documents() -> Iterator[dict[str, str]]:
    tenant_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'answers-verify-route.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-verify'))
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

            hidden_document = Document(
                tenant_id=tenant_id,
                owner_user_id=owner_a_id,
                title='Hidden Verify Source',
                source_type='loose_document',
                source_hash='hash-hidden-verify',
                file_name='hidden.txt',
                file_size_bytes=1,
                object_key='documents/hidden.txt',
                ingestion_status='completed',
            )
            session.add(hidden_document)
            session.flush()

            hidden_acl = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=hidden_document.owner_user_id,
                tenant_id=hidden_document.tenant_id,
                visibility='group',
                sensitivity='internal',
            )
            session.add(hidden_acl)
            session.flush()
            session.add_all(
                [
                    AclAllowedUser(acl_grant_id=hidden_acl.id, user_id=hidden_document.owner_user_id),
                    AclAllowedGroup(acl_grant_id=hidden_acl.id, group_id=group_a_id),
                ]
            )
            session.commit()

            hidden_document_id = str(hidden_document.id)

        try:
            yield {
                'database_url': database_url,
                'tenant_id': str(tenant_id),
                'user_b_id': str(user_b_id),
                'group_b_id': str(group_b_id),
                'hidden_document_id': hidden_document_id,
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def test_answers_verify_does_not_validate_hidden_group_a_content_for_group_b_user(
    seeded_verify_documents: dict[str, str],
) -> None:
    app = create_app(Settings(database_url=seeded_verify_documents['database_url'], llm_backend='stub', parser_backend=''))
    app.dependency_overrides[get_request_context] = lambda: RequestContext(
        tenant_id=seeded_verify_documents['tenant_id'],
        user_id=seeded_verify_documents['user_b_id'],
        group_ids=[seeded_verify_documents['group_b_id']],
        roles=['editor'],
        scopes=['documents:read'],
    )
    app.state.search_retriever = _AclVerifyRetrieverStub(hidden_document_id=seeded_verify_documents['hidden_document_id'])

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/answers/verify",
                json={
                    "question": "What happened?",
                    "answer_text": "Hidden evidence that should be filtered out.",
                    "top_k": 3,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    assert body["supported_sentence_count"] == 0
    assert body["insufficient_evidence_sentence_count"] == 1
