from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.base import session_factory
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.core.config import Settings
from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.main import create_app
from app.schemas.generation import GenerateAnswerResponse, TokenEvent


class _RetrieverStub:
    def __init__(
        self,
        *,
        text: str = "Visible evidence",
        document_id: str = "doc-1",
        chunk_id: str = "chunk-1",
    ) -> None:
        self.text = text
        self.document_id = document_id
        self.chunk_id = chunk_id

    def search(self, query) -> list[dict]:
        return [
            {
                "document_id": self.document_id,
                "chunk_id": self.chunk_id,
                "score": 0.9,
                "text": self.text,
                "page_start": 1,
                "page_end": 1,
                "heading_path": ["A"],
                "route": "semantic",
            }
        ]


class _EmptyRetrieverStub:
    def search(self, query) -> list[dict]:
        return []


class _FixedLlmBackend:
    def __init__(self, answer_text: str = "Visible evidence") -> None:
        self.calls: list[object] = []
        self._answer_text = answer_text

    def generate(self, request) -> GenerateAnswerResponse:
        self.calls.append(request)
        return GenerateAnswerResponse(
            answer_text=self._answer_text,
            model_name="stub-model",
            provider_name="stub",
            usage={"total_tokens": 7},
        )

    async def generate_stream(self, request):
        """Streaming stub: yields the full answer as a single token, then final."""
        self.calls.append(request)
        yield TokenEvent(text=self._answer_text, is_final=False)
        yield TokenEvent(text="", is_final=True, usage={"total_tokens": 7})


def _request_context() -> RequestContext:
    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        group_ids=[],
        roles=["editor"],
        scopes=["documents:read"],
    )


def _make_app(*, settings: Settings, retriever=None, llm_backend=None):
    app = create_app(settings)
    app.dependency_overrides[get_request_context] = _request_context
    if retriever is not None:
        app.state.search_retriever = retriever
    if llm_backend is not None:
        app.state.llm_backend = llm_backend
    return app


@pytest.fixture()
def seeded_chat_acl_documents():
    tenant_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'chat-acl-route.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-chat-acl'))
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
                title='Group A Secret',
                source_type='loose_document',
                source_hash='hash-group-a',
                file_name='group-a.txt',
                file_size_bytes=1,
                object_key='documents/group-a.txt',
                ingestion_status='completed',
            )
            visible_document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_b_id,
                title='Group B Visible',
                source_type='loose_document',
                source_hash='hash-group-b',
                file_name='group-b.txt',
                file_size_bytes=1,
                object_key='documents/group-b.txt',
                ingestion_status='completed',
            )
            session.add_all([hidden_document, visible_document])
            session.flush()
            hidden_document_id = str(hidden_document.id)

            hidden_acl = AclGrant(
                document_id=hidden_document.id,
                owner_user_id=hidden_document.owner_user_id,
                tenant_id=hidden_document.tenant_id,
                visibility='group',
                sensitivity='internal',
            )
            visible_acl = AclGrant(
                document_id=visible_document.id,
                owner_user_id=visible_document.owner_user_id,
                tenant_id=visible_document.tenant_id,
                visibility='group',
                sensitivity='internal',
            )
            session.add_all([hidden_acl, visible_acl])
            session.flush()
            session.add_all(
                [
                    AclAllowedUser(acl_grant_id=hidden_acl.id, user_id=hidden_document.owner_user_id),
                    AclAllowedUser(acl_grant_id=visible_acl.id, user_id=visible_document.owner_user_id),
                    AclAllowedGroup(acl_grant_id=hidden_acl.id, group_id=group_a_id),
                    AclAllowedGroup(acl_grant_id=visible_acl.id, group_id=group_b_id),
                ]
            )
            session.commit()

        llm_backend = _FixedLlmBackend()
        app = _make_app(
            settings=Settings(database_url=database_url, llm_backend='stub', parser_backend=''),
            retriever=_RetrieverStub(
                text='Group A only hidden evidence',
                document_id=hidden_document_id,
                chunk_id='chunk-hidden-a-1',
            ),
            llm_backend=llm_backend,
        )
        app.dependency_overrides[get_request_context] = lambda: RequestContext(
            tenant_id=str(tenant_id),
            user_id=str(user_b_id),
            group_ids=[str(group_b_id)],
            roles=['editor'],
            scopes=['documents:read'],
        )

        try:
            yield app, llm_backend
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()


def test_chat_route_returns_answer_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [type("DocRow", (), {"id": "doc-1", "title": "Doc A", "source_type": "loose_document"})()],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)
    app = _make_app(
        settings=Settings(llm_backend="stub"),
        retriever=_RetrieverStub(),
        llm_backend=_FixedLlmBackend(),
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"question": "What happened?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == "Visible evidence"
    assert body["status"] == "answered"
    assert body["provider_name"] == "stub"
    assert body["context_block_count"] == 1
    assert body["citations"][0]["citation_id"] == "chunk-1"
    assert body["verification"]["status"] == "supported"


def test_chat_stream_route_emits_real_streaming_events(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [type("DocRow", (), {"id": "doc-1", "title": "Doc A", "source_type": "loose_document"})()],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)
    app = _make_app(
        settings=Settings(llm_backend="stub"),
        retriever=_RetrieverStub(),
        llm_backend=_FixedLlmBackend(),
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={"question": "What happened?", "top_k": 3})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # New streaming format: retrieval -> token -> verification -> citations -> final -> done
    assert "event: retrieval" in response.text
    assert "event: token" in response.text
    assert "event: final" in response.text
    assert "event: done" in response.text


def test_chat_route_returns_503_when_retriever_missing() -> None:
    app = _make_app(settings=Settings(llm_backend="stub"), llm_backend=_FixedLlmBackend())

    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"question": "What happened?", "top_k": 3})

    assert response.status_code == 503
    assert response.json()["detail"] == "Search retrieval is not configured yet. Configure a search retriever before using /chat."


def test_chat_route_returns_503_when_llm_backend_disabled() -> None:
    app = _make_app(settings=Settings(llm_backend="disabled"), retriever=_RetrieverStub())

    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"question": "What happened?", "top_k": 3})

    assert response.status_code == 503
    assert response.json()["detail"] == "LLM generation is not configured yet. Configure an LLM backend before using /chat."


def test_non_streaming_and_streaming_produce_same_answer_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [type("DocRow", (), {"id": "doc-1", "title": "Doc A", "source_type": "loose_document"})()],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)
    app = _make_app(
        settings=Settings(llm_backend="stub"),
        retriever=_RetrieverStub(),
        llm_backend=_FixedLlmBackend(),
    )

    with TestClient(app) as client:
        non_streaming = client.post("/api/v1/chat", json={"question": "What happened?", "top_k": 3})
        streaming = client.post("/api/v1/chat/stream", json={"question": "What happened?", "top_k": 3})

    assert non_streaming.status_code == 200
    assert streaming.status_code == 200
    assert non_streaming.json()["answer_text"] == "Visible evidence"
    # Streaming now emits token events; the answer text appears in the final event
    assert '"answer_text":"Visible evidence"' in streaming.text


def test_chat_route_returns_not_enough_evidence_and_skips_llm_when_search_has_no_hits(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.search_service.list_documents_for_context", lambda **kwargs: [])
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)
    llm_backend = _FixedLlmBackend()
    app = _make_app(
        settings=Settings(llm_backend="stub"),
        retriever=_EmptyRetrieverStub(),
        llm_backend=llm_backend,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"question": "What happened?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == "I do not have enough permitted source evidence to answer that yet."
    assert body["status"] == "not_enough_evidence"
    assert body["model_name"] is None
    assert body["provider_name"] is None
    assert body["context_block_count"] == 0
    assert body["retrieval_hit_count"] == 0
    assert body["usage"] is None
    assert body["citations"] == []
    assert body["verification"] is None
    assert llm_backend.calls == []


def test_chat_stream_route_returns_not_enough_evidence_and_skips_llm_when_search_has_no_hits(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.search_service.list_documents_for_context", lambda **kwargs: [])
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)
    monkeypatch.setattr("app.services.chat_service.write_audit_event", lambda **kwargs: None)
    llm_backend = _FixedLlmBackend()
    app = _make_app(
        settings=Settings(llm_backend="stub"),
        retriever=_EmptyRetrieverStub(),
        llm_backend=llm_backend,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={"question": "What happened?", "top_k": 3})

    assert response.status_code == 200
    # New streaming format: retrieval -> final (not_enough_evidence) -> done
    assert 'event: final' in response.text
    assert '"status":"not_enough_evidence"' in response.text
    assert llm_backend.calls == []


@pytest.mark.parametrize("endpoint", ["/api/v1/chat", "/api/v1/chat/stream"])
def test_chat_routes_do_not_answer_from_group_a_only_content_for_group_b_user(
    seeded_chat_acl_documents,
    endpoint: str,
) -> None:
    app, llm_backend = seeded_chat_acl_documents

    with TestClient(app) as client:
        response = client.post(endpoint, json={"question": "What is in the hidden document?", "top_k": 3})

    assert response.status_code == 200
    assert llm_backend.calls == []

    if endpoint == "/api/v1/chat":
        assert response.json()["status"] == "not_enough_evidence"
        assert response.json()["answer_text"] == "I do not have enough permitted source evidence to answer that yet."
        assert response.json()["retrieval_hit_count"] == 0
        return

    # Streaming endpoint: new format uses 'final' event instead of 'answer'
    assert 'event: final' in response.text
    assert '"status":"not_enough_evidence"' in response.text
    assert '"hit_count":0' in response.text


@pytest.fixture()
def chat_audit_app():
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'chat-route.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-chat'))
            session.add(User(id=user_id, tenant_id=tenant_id, email='reader@example.com', display_name='Reader', roles=['editor']))
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title='Doc A',
                source_type='loose_document',
                source_hash='hash-chat',
                file_name='chat.txt',
                file_size_bytes=1,
                object_key='documents/chat.txt',
                ingestion_status='completed',
            )
            session.add(document)
            session.flush()
            session.add(
                AclGrant(
                    document_id=document.id,
                    owner_user_id=user_id,
                    tenant_id=tenant_id,
                    visibility='private',
                    sensitivity='internal',
                )
            )
            session.commit()

        doc_row = type("DocRow", (), {"id": "doc-1", "title": "Doc A", "source_type": "loose_document"})()
        llm_backend = _FixedLlmBackend()
        app = _make_app(
            settings=Settings(database_url=database_url, llm_backend='stub', parser_backend=''),
            retriever=_RetrieverStub(),
            llm_backend=llm_backend,
        )
        app.dependency_overrides[get_request_context] = lambda: RequestContext(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            group_ids=[],
            roles=['editor'],
            scopes=['documents:read'],
        )

        try:
            yield app, engine, doc_row
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()


def test_chat_routes_write_non_sensitive_chat_audit_events(chat_audit_app, monkeypatch) -> None:
    app, engine, doc_row = chat_audit_app
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [doc_row],
    )

    with TestClient(app) as client:
        non_streaming = client.post('/api/v1/chat', json={'question': 'What happened?', 'top_k': 3})
        streaming = client.post('/api/v1/chat/stream', json={'question': 'What happened?', 'top_k': 3})

    assert non_streaming.status_code == 200
    assert streaming.status_code == 200

    session_factory.configure(bind=engine)
    with session_factory() as session:
        audit_events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == 'chat.answer')
            .order_by(AuditEvent.timestamp.asc())
        ).all()

    # Only the non-streaming route writes audit events now (streaming doesn't call answer())
    assert len(audit_events) >= 1
    assert audit_events[0].details['delivery_mode'] == 'blocking'
    assert audit_events[0].details['query_sha256'] == 'c4dc542b511fd74f401665a02dd5a20cf41cebd16daa6a7f78ddfbcce88239fe'
    assert audit_events[0].details['retrieved_document_ids'] == ['doc-1']
    assert audit_events[0].details['llm_invoked'] is True
    assert audit_events[0].details['provider_name'] == 'stub'
    assert 'question' not in audit_events[0].details
    assert 'answer_text' not in audit_events[0].details
