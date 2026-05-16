from __future__ import annotations

import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import get_settings
from app.core.config import Settings
from app.db.base import session_factory
from app.db.models.acl import AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.services.parsers.docling_backend import DoclingDocumentParser
import app.main as main_module


def _reload_app_module() -> ModuleType:
    get_settings.cache_clear()
    return importlib.reload(main_module)


def _dev_auth_headers(*, tenant_id: str, user_id: str, scopes: list[str]) -> dict[str, str]:
    return {
        "X-Dev-Auth-Tenant-Id": tenant_id,
        "X-Dev-Auth-User-Id": user_id,
        "X-Dev-Auth-Scopes": ",".join(scopes),
        "X-Dev-Auth-Roles": "editor",
        "X-Dev-Auth-Groups": "",
    }


def test_dev_header_auth_allows_real_runtime_list_without_dependency_override(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-auth.db'}"
        storage_dir = Path(tmp_dir) / "storage"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="runtime-auth-tenant"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="runtime@example.com",
                    display_name="Runtime User",
                    roles=["editor"],
                )
            )
            document = Document(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title="Runtime Visible",
                source_type="loose_document",
                source_hash="runtime-hash",
                file_name="runtime.txt",
                file_size_bytes=1,
                object_key="documents/runtime.txt",
                ingestion_status="uploaded",
            )
            session.add(document)
            session.flush()
            acl_grant = AclGrant(
                document_id=document.id,
                owner_user_id=user_id,
                tenant_id=tenant_id,
                visibility="private",
                sensitivity="internal",
            )
            session.add(acl_grant)
            session.flush()
            session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=user_id))
            session.commit()

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers=_dev_auth_headers(
                        tenant_id=str(tenant_id),
                        user_id=str(user_id),
                        scopes=["documents:read"],
                    ),
                )

            assert response.status_code == 200
            assert [item["title"] for item in response.json()["items"]] == ["Runtime Visible"]
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_dev_header_auth_rejects_non_loopback_runtime_requests(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-auth-remote.db'}"
        storage_dir = Path(tmp_dir) / "storage"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="runtime-auth-remote-tenant"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="remote@example.com",
                    display_name="Remote User",
                    roles=["editor"],
                )
            )
            session.commit()

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("203.0.113.10", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers=_dev_auth_headers(
                        tenant_id=str(tenant_id),
                        user_id=str(user_id),
                        scopes=["documents:read"],
                    ),
                )

            assert response.status_code == 403
            assert response.json() == {
                "detail": "Development authentication is only available from loopback clients. Use localhost for local development or configure production authentication.",
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_dev_headers_do_not_authenticate_oidc_runtime(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()

    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-auth-oidc.db'}"
        storage_dir = Path(tmp_dir) / "storage"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)
        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Tenant", slug="runtime-auth-oidc-tenant"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email="oidc-mode@example.com",
                    display_name="OIDC Mode User",
                    roles=["editor"],
                )
            )
            session.commit()

        monkeypatch.setenv("AUTH_MODE", "oidc")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("OIDC_ISSUER_URL", "http://localhost:8080/realms/uber-rag")
        monkeypatch.setenv("OIDC_AUDIENCE", "uber-rag-api")
        monkeypatch.setenv("OIDC_JWKS_URL", "http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs")
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers=_dev_auth_headers(
                        tenant_id=str(tenant_id),
                        user_id=str(user_id),
                        scopes=["documents:read"],
                    ),
                )

            assert response.status_code == 401
            assert response.json() == {"detail": "Missing bearer token"}
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_app_startup_wires_session_factory_and_local_storage_adapter(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50001)):
                assert session_factory.kw.get("bind") is not None
                assert hasattr(reloaded_main.app.state, "document_storage")
                assert isinstance(reloaded_main.app.state.dispatcher._parser, DoclingDocumentParser)
                assert reloaded_main.app.state.dispatcher._parser._storage_root == storage_dir
                assert reloaded_main.app.state.dispatcher._parser_backend == "docling-local"
                assert reloaded_main.app.state.dispatcher._parser_profile == "local-cpu"
                assert storage_dir.exists()
        finally:
            session_factory.configure(bind=None)


def test_app_startup_builds_dispatcher_from_parser_factory(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup-factory.db'}"
        storage_dir = Path(tmp_dir) / "storage"
        factory_result = (
            DoclingDocumentParser(storage_root=storage_dir),
            "factory-backend",
            "factory-profile",
        )

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        reloaded_main = _reload_app_module()
        monkeypatch.setattr(reloaded_main, "build_document_parser", lambda settings: factory_result)

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50002)):
                assert reloaded_main.app.state.dispatcher._parser is factory_result[0]
                assert reloaded_main.app.state.dispatcher._parser_backend == "factory-backend"
                assert reloaded_main.app.state.dispatcher._parser_profile == "factory-profile"
        finally:
            session_factory.configure(bind=None)


def test_app_startup_fails_fast_for_seaweedfs_with_local_docling_runtime(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup-seaweedfs-docling.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("STORAGE_BACKEND", "seaweedfs")
        monkeypatch.setenv("PARSER_BACKEND", "docling")
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50003)):
                raise AssertionError("startup should fail before serving requests")
        except RuntimeError as exc:
            message = str(exc)
            assert "SeaweedFS object storage is not yet compatible with the local Docling parser runtime" in message
            assert "current parser expects files readable from local disk" in message
            assert "use local storage for now, or implement remote object-read parsing first" in message
        finally:
            session_factory.configure(bind=None)


def test_create_app_lifespan_uses_injected_settings_over_global_env(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        injected_database_url = f"sqlite:///{Path(tmp_dir) / 'injected.db'}"
        injected_storage_dir = Path(tmp_dir) / "injected-storage"
        env_storage_dir = Path(tmp_dir) / "env-storage"

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{Path(tmp_dir) / 'env.db'}")
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(env_storage_dir))

        custom_app = main_module.create_app(
            Settings(
                auth_mode="dev",
                database_url=injected_database_url,
                local_storage_dir=str(injected_storage_dir),
            )
        )

        try:
            with TestClient(custom_app, client=("127.0.0.1", 50002)):
                assert session_factory.kw.get("bind") is not None
                assert hasattr(custom_app.state, "document_storage")
                assert injected_storage_dir.exists()
                assert not env_storage_dir.exists()
        finally:
            session_factory.configure(bind=None)
