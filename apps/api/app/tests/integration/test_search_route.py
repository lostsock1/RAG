from __future__ import annotations

import hashlib
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

from app.core.config import Settings
from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.audit import AuditEvent
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app, create_app


class RetrieverStub:
    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.queries: list[object] = []

    def search(self, query) -> list[dict]:
        self.queries.append(query)
        return list(self.hits)


@pytest.fixture()
def seeded_search_documents() -> dict[str, str]:
    tenant_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-route.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-search'))
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

            documents: dict[str, Document] = {
                'group_a': Document(
                    tenant_id=tenant_id,
                    owner_user_id=owner_a_id,
                    title='Group A Secret',
                    source_type='loose_document',
                    source_hash='hash-a',
                    file_name='a.txt',
                    file_size_bytes=1,
                    object_key='documents/a.txt',
                    ingestion_status='completed',
                ),
                'group_b': Document(
                    tenant_id=tenant_id,
                    owner_user_id=user_b_id,
                    title='Group B Visible',
                    source_type='loose_document',
                    source_hash='hash-b',
                    file_name='b.txt',
                    file_size_bytes=1,
                    object_key='documents/b.txt',
                    ingestion_status='completed',
                ),
                'tenant_shared': Document(
                    tenant_id=tenant_id,
                    owner_user_id=owner_a_id,
                    title='Tenant Shared',
                    source_type='loose_document',
                    source_hash='hash-tenant',
                    file_name='tenant.txt',
                    file_size_bytes=1,
                    object_key='documents/tenant.txt',
                    ingestion_status='completed',
                ),
                'public_shared': Document(
                    tenant_id=tenant_id,
                    owner_user_id=owner_a_id,
                    title='Tenant Authenticated Public',
                    source_type='loose_document',
                    source_hash='hash-public',
                    file_name='public.txt',
                    file_size_bytes=1,
                    object_key='documents/public.txt',
                    ingestion_status='completed',
                ),
            }

            for key, document in documents.items():
                session.add(document)
                session.flush()
                visibility = 'tenant' if key == 'tenant_shared' else 'public' if key == 'public_shared' else 'group'
                acl_grant = AclGrant(
                    document_id=document.id,
                    owner_user_id=document.owner_user_id,
                    tenant_id=document.tenant_id,
                    visibility=visibility,
                    sensitivity='internal',
                )
                session.add(acl_grant)
                session.flush()
                session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=document.owner_user_id))
                if key == 'group_a':
                    session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_a_id))
                if key == 'group_b':
                    session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_b_id))

            session.commit()

            result = {
                'tenant_id': str(tenant_id),
                'owner_a_id': str(owner_a_id),
                'user_b_id': str(user_b_id),
                'group_a_id': str(group_a_id),
                'group_b_id': str(group_b_id),
                'group_a_document_id': str(documents['group_a'].id),
                'group_b_document_id': str(documents['group_b'].id),
                'tenant_shared_document_id': str(documents['tenant_shared'].id),
                'public_shared_document_id': str(documents['public_shared'].id),
            }

        try:
            yield result
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, 'search_retriever'):
                delattr(app.state, 'search_retriever')
            session_factory.configure(bind=None)
            engine.dispose()


def make_client(context: RequestContext, retriever: RetrieverStub | None = None) -> TestClient:
    app.dependency_overrides[get_request_context] = lambda: context
    if retriever is None:
        if hasattr(app.state, 'search_retriever'):
            delattr(app.state, 'search_retriever')
    else:
        app.state.search_retriever = retriever
    return TestClient(app)


def test_search_returns_acl_safe_ranked_hits_and_audit_event(seeded_search_documents: dict[str, str]) -> None:
    query_text = 'visible content'
    retriever = RetrieverStub(
        hits=[
            {
                'document_id': seeded_search_documents['group_b_document_id'],
                'chunk_id': 'chunk-b-1',
                'score': 0.91,
                'text': 'Visible group-b hit',
                'page_start': 3,
                'page_end': 3,
                'heading_path': ['Section B'],
            },
            {
                'document_id': seeded_search_documents['tenant_shared_document_id'],
                'chunk_id': 'chunk-t-1',
                'score': 0.77,
                'text': 'Tenant-wide hit',
                'page_start': 1,
                'page_end': 1,
                'heading_path': ['Shared'],
            },
            {
                'document_id': seeded_search_documents['public_shared_document_id'],
                'chunk_id': 'chunk-p-1',
                'score': 0.72,
                'text': 'Public within tenant hit',
                'page_start': 4,
                'page_end': 4,
                'heading_path': ['Public'],
            },
        ]
    )
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_documents['tenant_id'],
            user_id=seeded_search_documents['user_b_id'],
            group_ids=[seeded_search_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        ),
        retriever,
    )

    response = client.post('/api/v1/search', json={'query': query_text, 'top_k': 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 3
    assert [item['document_title'] for item in payload['items']] == ['Group B Visible', 'Tenant Shared', 'Tenant Authenticated Public']
    assert payload['items'][0]['citation_id'] == 'chunk-b-1'
    assert payload['items'][0]['source_viewer_url'] == '/api/v1/search/sources/chunk-b-1'
    assert payload['items'][0]['route'] == 'semantic'
    assert set(retriever.queries[0].allowed_document_ids) == {
        seeded_search_documents['group_b_document_id'],
        seeded_search_documents['tenant_shared_document_id'],
        seeded_search_documents['public_shared_document_id'],
    }

    with session_factory() as session:
        audit_event = session.scalar(select(AuditEvent).where(AuditEvent.action == 'search.query'))
        assert audit_event is not None
        assert audit_event.details['query_sha256'] == hashlib.sha256(query_text.encode('utf-8')).hexdigest()
        assert 'query' not in audit_event.details
        assert audit_event.details['result_document_ids'] == [
            seeded_search_documents['group_b_document_id'],
            seeded_search_documents['tenant_shared_document_id'],
            seeded_search_documents['public_shared_document_id'],
        ]


def test_search_filters_unauthorized_hits_even_if_retriever_returns_them(seeded_search_documents: dict[str, str]) -> None:
    retriever = RetrieverStub(
        hits=[
            {
                'document_id': seeded_search_documents['group_a_document_id'],
                'chunk_id': 'chunk-a-1',
                'score': 0.99,
                'text': 'Should be filtered',
                'page_start': 9,
                'page_end': 9,
                'heading_path': ['Secret'],
            },
            {
                'document_id': seeded_search_documents['group_b_document_id'],
                'chunk_id': 'chunk-b-1',
                'score': 0.55,
                'text': 'Visible hit',
                'page_start': 2,
                'page_end': 2,
                'heading_path': ['Visible'],
            },
        ]
    )
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_documents['tenant_id'],
            user_id=seeded_search_documents['user_b_id'],
            group_ids=[seeded_search_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        ),
        retriever,
    )

    response = client.post('/api/v1/search', json={'query': 'secret', 'top_k': 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 1
    assert [item['document_title'] for item in payload['items']] == ['Group B Visible']
    assert all(item['document_id'] != seeded_search_documents['group_a_document_id'] for item in payload['items'])


def test_search_returns_empty_items_when_no_hits(seeded_search_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_documents['tenant_id'],
            user_id=seeded_search_documents['user_b_id'],
            group_ids=[seeded_search_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        ),
        RetrieverStub(hits=[]),
    )

    response = client.post('/api/v1/search', json={'query': 'missing phrase', 'top_k': 5})

    assert response.status_code == 200
    assert response.json() == {'items': [], 'total': 0}


def test_search_rejects_whitespace_only_query_with_422(seeded_search_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_documents['tenant_id'],
            user_id=seeded_search_documents['user_b_id'],
            group_ids=[seeded_search_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        ),
        RetrieverStub(hits=[]),
    )

    response = client.post('/api/v1/search', json={'query': '   \t\n  ', 'top_k': 5})

    assert response.status_code == 422
    assert any(
        'whitespace' in err['msg'].lower() or 'blank' in err['msg'].lower()
        for err in response.json()['detail']
    )


def test_search_returns_503_when_retriever_is_not_configured(seeded_search_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_documents['tenant_id'],
            user_id=seeded_search_documents['user_b_id'],
            group_ids=[seeded_search_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    response = client.post('/api/v1/search', json={'query': 'anything', 'top_k': 5})

    assert response.status_code == 503
    assert response.json() == {
        'detail': 'Search retrieval is not configured yet. Configure a search retriever before using /search.'
    }


def test_search_uses_runtime_wired_hybrid_retriever_when_search_is_configured() -> None:
    class _FakeOpenSearchClient:
        def __init__(self, document_id: str, chunk_id: str) -> None:
            self.document_id = document_id
            self.chunk_id = chunk_id

        def search(self, *, index: str, body: dict) -> dict:
            assert body['query']['bool']['must'] == [{'match_phrase': {'text': 'visible exact'}}]
            return {
                'hits': {
                    'hits': [
                        {
                            '_score': 1.5,
                            '_source': {
                                'document_id': self.document_id,
                                'chunk_id': self.chunk_id,
                                'chunk_index': 1,
                                'text': 'Visible exact text',
                                'page_start': 2,
                                'page_end': 2,
                                'heading_path': ['Quoted'],
                            },
                        }
                    ]
                }
            }

    class _FakeQdrantClient:
        def query_points(self, **kwargs: object) -> list[object]:
            return []

    class _FakeQueryEmbedder:
        def embed_query(self, query: str) -> dict[str, object]:
            return {'dense': [0.1, 0.2], 'sparse': {'indices': [1], 'values': [0.8]}}

    tenant_id = uuid4()
    user_id = uuid4()
    group_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-runtime.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-search-runtime'))
            session.add(User(id=user_id, tenant_id=tenant_id, email='user@example.com', display_name='User', roles=['editor']))
            session.add(Group(id=group_id, tenant_id=tenant_id, name='group-search'))
            session.add(UserGroup(user_id=user_id, group_id=group_id))

            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title='Runtime Search Doc',
                source_type='loose_document',
                source_hash='hash-runtime',
                file_name='runtime.txt',
                file_size_bytes=1,
                object_key='documents/runtime.txt',
                ingestion_status='completed',
            )
            session.add(document)
            session.flush()
            acl_grant = AclGrant(
                document_id=document.id,
                owner_user_id=user_id,
                tenant_id=tenant_id,
                visibility='group',
                sensitivity='internal',
            )
            session.add(acl_grant)
            session.flush()
            session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=user_id))
            session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_id))
            search_chunk = Chunk(
                document_id=document.id,
                unit_type='paragraph',
                heading_path=['Quoted'],
                page_start=2,
                page_end=2,
                text='Visible exact text',
                parent_id=uuid4(),
                chunk_index=1,
            )
            session.add(search_chunk)
            session.commit()
            document_id = str(document.id)
            chunk_id = str(search_chunk.id)

        custom_app = create_app(
            Settings(
                auth_mode='dev',
                database_url=database_url,
                local_storage_dir=str(Path(tmp_dir) / 'storage'),
                search_backend='hybrid',
                opensearch_index_name='chunks-test',
                qdrant_collection_name='chunks-test',
            )
        )
        custom_app.dependency_overrides[get_request_context] = lambda: RequestContext(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            group_ids=[str(group_id)],
            roles=['editor'],
            scopes=['documents:read'],
        )
        custom_app.state.search_lexical_client = _FakeOpenSearchClient(document_id, chunk_id)
        custom_app.state.search_vector_client = _FakeQdrantClient()
        custom_app.state.search_query_embedder = _FakeQueryEmbedder()

        try:
            with TestClient(custom_app) as client:
                response = client.post('/api/v1/search', json={'query': '"visible exact"', 'top_k': 5})

                assert hasattr(custom_app.state, 'search_retriever')
                assert response.status_code == 200
                payload = response.json()
                assert payload['items'][0]['document_title'] == 'Runtime Search Doc'
                assert payload['items'][0]['chunk_id'] == chunk_id
                assert payload['items'][0]['source_viewer_url'] == f'/api/v1/search/sources/{chunk_id}'

                source_response = client.get(f'/api/v1/search/sources/{chunk_id}')

                assert source_response.status_code == 200
                assert source_response.json()['focus_chunk_id'] == chunk_id
        finally:
            custom_app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()
