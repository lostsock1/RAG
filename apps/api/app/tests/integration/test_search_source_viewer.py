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

from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.acl_models import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.base import session_factory
from app.db.models.audit import AuditEvent
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app


@pytest.fixture()
def seeded_search_source_viewer_documents() -> dict[str, str]:
    tenant_id = uuid4()
    owner_a_id = uuid4()
    user_b_id = uuid4()
    group_a_id = uuid4()
    group_b_id = uuid4()
    visible_parent_id = uuid4()
    visible_child_before_id = uuid4()
    visible_child_focus_id = uuid4()
    visible_child_after_id = uuid4()
    hidden_child_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-source-viewer.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant One', slug='tenant-search-source-viewer'))
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
                title='Visible Search Source',
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
                title='Hidden Search Source',
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
                        id=visible_parent_id,
                        document_id=visible_document.id,
                        unit_type='section',
                        heading_path=['Root'],
                        page_start=1,
                        page_end=2,
                        text='Visible parent section',
                        parent_id=None,
                        chunk_index=0,
                    ),
                    Chunk(
                        id=visible_child_before_id,
                        document_id=visible_document.id,
                        unit_type='paragraph',
                        heading_path=['Root', 'Before'],
                        page_start=1,
                        page_end=1,
                        text='Visible context before',
                        parent_id=visible_parent_id,
                        chunk_index=1,
                    ),
                    Chunk(
                        id=visible_child_focus_id,
                        document_id=visible_document.id,
                        unit_type='paragraph',
                        heading_path=['Root', 'Focus'],
                        page_start=2,
                        page_end=2,
                        text='Visible focus chunk',
                        parent_id=visible_parent_id,
                        chunk_index=2,
                    ),
                    Chunk(
                        id=visible_child_after_id,
                        document_id=visible_document.id,
                        unit_type='paragraph',
                        heading_path=['Root', 'After'],
                        page_start=2,
                        page_end=2,
                        text='Visible context after',
                        parent_id=visible_parent_id,
                        chunk_index=3,
                    ),
                    Chunk(
                        id=hidden_child_id,
                        document_id=hidden_document.id,
                        unit_type='paragraph',
                        heading_path=['Secret'],
                        page_start=4,
                        page_end=4,
                        text='Hidden focus chunk',
                        parent_id=None,
                        chunk_index=0,
                    ),
                ]
            )
            session.commit()

            result = {
                'tenant_id': str(tenant_id),
                'user_b_id': str(user_b_id),
                'group_b_id': str(group_b_id),
                'visible_document_id': str(visible_document.id),
                'visible_parent_id': str(visible_parent_id),
                'visible_child_before_id': str(visible_child_before_id),
                'visible_child_focus_id': str(visible_child_focus_id),
                'visible_child_after_id': str(visible_child_after_id),
                'hidden_child_id': str(hidden_child_id),
            }

        try:
            yield result
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()


def make_client(context: RequestContext) -> TestClient:
    app.dependency_overrides[get_request_context] = lambda: context
    return TestClient(app)


def test_source_viewer_returns_chunk_with_surrounding_context(
    seeded_search_source_viewer_documents: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_source_viewer_documents['tenant_id'],
            user_id=seeded_search_source_viewer_documents['user_b_id'],
            group_ids=[seeded_search_source_viewer_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    response = client.get(
        f"/api/v1/search/sources/{seeded_search_source_viewer_documents['visible_child_focus_id']}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['citation_id'] == seeded_search_source_viewer_documents['visible_child_focus_id']
    assert payload['document_id'] == seeded_search_source_viewer_documents['visible_document_id']
    assert payload['focus_chunk_id'] == seeded_search_source_viewer_documents['visible_child_focus_id']
    assert payload['parent_chunk_id'] == seeded_search_source_viewer_documents['visible_parent_id']
    assert [item['chunk_id'] for item in payload['items']] == [
        seeded_search_source_viewer_documents['visible_child_before_id'],
        seeded_search_source_viewer_documents['visible_child_focus_id'],
        seeded_search_source_viewer_documents['visible_child_after_id'],
    ]
    assert payload['items'][1]['is_focus'] is True


def test_source_viewer_returns_404_for_inaccessible_chunk(
    seeded_search_source_viewer_documents: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_source_viewer_documents['tenant_id'],
            user_id=seeded_search_source_viewer_documents['user_b_id'],
            group_ids=[seeded_search_source_viewer_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    response = client.get(
        f"/api/v1/search/sources/{seeded_search_source_viewer_documents['hidden_child_id']}"
    )

    assert response.status_code == 404
    assert response.json() == {
        'detail': 'Search source was not found or you do not have access to it.'
    }

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == 'search.source.view.denied')
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id is None
    assert audit_event.details == {
        'citation_id': seeded_search_source_viewer_documents['hidden_child_id'],
        'reason': 'not_found_or_denied',
    }



def test_source_viewer_returns_404_and_audits_missing_chunk(
    seeded_search_source_viewer_documents: dict[str, str],
) -> None:
    missing_chunk_id = str(uuid4())
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_source_viewer_documents['tenant_id'],
            user_id=seeded_search_source_viewer_documents['user_b_id'],
            group_ids=[seeded_search_source_viewer_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    response = client.get(f'/api/v1/search/sources/{missing_chunk_id}')

    assert response.status_code == 404
    assert response.json() == {
        'detail': 'Search source was not found or you do not have access to it.'
    }

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == 'search.source.view.denied')
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id is None
    assert audit_event.details == {
        'citation_id': missing_chunk_id,
        'reason': 'not_found_or_denied',
    }


def test_source_viewer_is_focus_true_when_chunk_id_has_no_hyphens(
    seeded_search_source_viewer_documents: dict[str, str],
) -> None:
    """is_focus must be True when the URL chunk_id parameter uses a different
    UUID formatting than the canonical hyphenated form stored in the database."""
    focus_id = seeded_search_source_viewer_documents['visible_child_focus_id']
    # Strip hyphens to simulate a non-canonical but equivalent UUID string
    focus_id_no_hyphens = focus_id.replace('-', '')

    client = make_client(
        RequestContext(
            tenant_id=seeded_search_source_viewer_documents['tenant_id'],
            user_id=seeded_search_source_viewer_documents['user_b_id'],
            group_ids=[seeded_search_source_viewer_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    response = client.get(f'/api/v1/search/sources/{focus_id_no_hyphens}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['focus_chunk_id'] == focus_id
    # The focus chunk must be marked is_focus=True even though the URL
    # used the non-hyphenated UUID form.
    focus_item = next(item for item in payload['items'] if item['chunk_id'] == focus_id)
    assert focus_item['is_focus'] is True
