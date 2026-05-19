from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app
from app.repositories.acl_policy import lock_tenant_acl_policy


@pytest.fixture()
def seeded_acl_policy_tenant() -> dict[str, str]:
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'acl-bootstrap-route.db'}"
        engine = create_engine(database_url)
        config = Config(str(Path('infra/migrations/alembic.ini')))
        config.set_main_option('sqlalchemy.url', database_url)

        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name='Tenant', slug='tenant-acl-bootstrap-route'))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email='user@example.com',
                    display_name='User',
                    roles=['editor'],
                )
            )
            session.commit()

        try:
            yield {'tenant_id': str(tenant_id), 'user_id': str(user_id)}
        finally:
            app.dependency_overrides.clear()
            session_factory.configure(bind=None)
            engine.dispose()


def make_client(context: RequestContext) -> TestClient:
    app.dependency_overrides[get_request_context] = lambda: context
    return TestClient(app)


def test_get_acl_bootstrap_policy_returns_not_found_before_configuration(
    seeded_acl_policy_tenant: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    response = client.get('/api/v1/acl/bootstrap-policy')

    assert response.status_code == 404
    assert response.json()['detail'] == 'ACL bootstrap policy has not been configured for this tenant yet.'


def test_put_then_get_acl_bootstrap_policy_exposes_public_api_configuration(
    seeded_acl_policy_tenant: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:read', 'documents:write'],
        )
    )

    put_response = client.put(
        '/api/v1/acl/bootstrap-policy',
        json={
            'default_visibility_mode': 'public',
            'visibility_display_names': {'public': 'Authenticated Tenant Users'},
            'visibility_active_flags': {'public': True},
            'sensitivity_display_names': {'internal': 'Internal Only'},
            'dimension_display_names': {'group': 'Department'},
            'dimension_active_flags': {'project': True},
        },
    )

    assert put_response.status_code == 200
    put_payload = put_response.json()
    assert put_payload['status'] == 'draft'
    assert put_payload['default_visibility_mode'] == 'public'
    assert put_payload['visibility_modes']['public']['display_name'] == 'Authenticated Tenant Users'
    assert put_payload['dimensions']['project']['is_active'] is True

    get_response = client.get('/api/v1/acl/bootstrap-policy')

    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert UUID(get_payload['tenant_id']) == UUID(seeded_acl_policy_tenant['tenant_id'])
    assert get_payload['default_visibility_mode'] == 'public'
    assert get_payload['sensitivity_levels']['internal']['display_name'] == 'Internal Only'


def test_put_acl_bootstrap_policy_returns_conflict_when_locked(
    seeded_acl_policy_tenant: dict[str, str],
) -> None:
    lock_tenant_acl_policy(tenant_id=UUID(seeded_acl_policy_tenant['tenant_id']))
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:write'],
        )
    )

    response = client.put('/api/v1/acl/bootstrap-policy', json={'default_visibility_mode': 'tenant'})

    assert response.status_code == 409
    assert response.json()['detail'] == 'ACL bootstrap policy is locked because ingestion has already started for this tenant.'


def test_put_acl_bootstrap_policy_returns_validation_error_for_inactive_default(
    seeded_acl_policy_tenant: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:write'],
        )
    )

    response = client.put(
        '/api/v1/acl/bootstrap-policy',
        json={
            'default_visibility_mode': 'public',
            'visibility_active_flags': {'public': False},
        },
    )

    assert response.status_code == 422
    assert response.json()['detail'] == "ACL policy default visibility 'public' must be active."


def test_put_acl_bootstrap_policy_returns_validation_error_for_unknown_visibility_key(
    seeded_acl_policy_tenant: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:write'],
        )
    )

    response = client.put(
        '/api/v1/acl/bootstrap-policy',
        json={
            'visibility_display_names': {'bogus': 'Broken'},
        },
    )

    assert response.status_code == 422
    assert response.json()['detail'] == (
        "Unknown ACL policy visibility_display_names key(s): bogus. Allowed keys: group, private, public, tenant."
    )


def test_put_acl_bootstrap_policy_returns_validation_error_for_unknown_default_visibility(
    seeded_acl_policy_tenant: dict[str, str],
) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:write'],
        )
    )

    response = client.put(
        '/api/v1/acl/bootstrap-policy',
        json={
            'default_visibility_mode': 'bogus',
        },
    )

    assert response.status_code == 422
    assert response.json()['detail'] == (
        "Unknown ACL policy default visibility 'bogus'. Allowed keys: group, private, public, tenant."
    )


def test_acl_bootstrap_policy_route_enforces_scopes(seeded_acl_policy_tenant: dict[str, str]) -> None:
    readless_client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=[],
        )
    )

    assert readless_client.get('/api/v1/acl/bootstrap-policy').status_code == 403

    write_less_client = make_client(
        RequestContext(
            tenant_id=seeded_acl_policy_tenant['tenant_id'],
            user_id=seeded_acl_policy_tenant['user_id'],
            group_ids=[],
            roles=['editor'],
            scopes=['documents:read'],
        )
    )

    assert write_less_client.put('/api/v1/acl/bootstrap-policy', json={}).status_code == 403
