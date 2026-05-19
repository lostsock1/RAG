from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.models.tenant import Tenant
from app.repositories.acl_policy import (
    AclPolicyLockedError,
    configure_tenant_acl_policy,
    get_tenant_acl_policy,
    lock_tenant_acl_policy,
)


@pytest.fixture()
def seeded_tenant():
    tenant_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'acl-policy.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-acl-policy"))
            session.commit()

        try:
            yield tenant_id
        finally:
            session_factory.configure(bind=None)
            engine.dispose()


def test_configure_tenant_acl_policy_persists_draft_defaults_and_custom_labels(seeded_tenant) -> None:
    policy = configure_tenant_acl_policy(
        tenant_id=seeded_tenant,
        default_visibility_mode="group",
        visibility_display_names={"group": "Team", "tenant": "Company"},
        visibility_active_flags={"public": False},
        sensitivity_display_names={"internal": "Staff Only"},
        dimension_display_names={"group": "Department", "project": "Matter"},
        dimension_active_flags={"project": True},
    )

    assert policy.status == "draft"
    assert policy.default_visibility_mode == "group"
    assert policy.visibility_modes["group"].display_name == "Team"
    assert policy.visibility_modes["public"].is_active is False
    assert policy.sensitivity_levels["internal"].display_name == "Staff Only"
    assert policy.sensitivity_levels["restricted"].rank == 400
    assert policy.dimensions["user"].is_active is True
    assert policy.dimensions["group"].display_name == "Department"
    assert policy.dimensions["project"].display_name == "Matter"
    assert policy.dimensions["project"].is_active is True
    assert policy.dimensions["role"].is_active is False
    assert get_tenant_acl_policy(tenant_id=seeded_tenant).policy_id == policy.policy_id


def test_locked_acl_policy_rejects_semantic_updates(seeded_tenant) -> None:
    configure_tenant_acl_policy(tenant_id=seeded_tenant)
    locked_policy = lock_tenant_acl_policy(tenant_id=seeded_tenant)

    assert locked_policy.status == "locked"
    assert locked_policy.locked_at is not None

    with pytest.raises(AclPolicyLockedError):
        configure_tenant_acl_policy(
            tenant_id=seeded_tenant,
            default_visibility_mode="tenant",
        )
