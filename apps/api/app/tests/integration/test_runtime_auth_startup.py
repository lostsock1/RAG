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
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import get_settings
from app.core.config import Settings
from app.db.base import session_factory
from app.db.models.acl import AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParserProvenance
from app.services.parsers.base import ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser
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


def test_app_startup_uses_remote_api_ocr_defaults_for_remote_profile(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup-remote-factory.db'}"
        storage_dir = Path(tmp_dir) / "storage"
        factory_result = (
            RemoteDocumentParser(
                invoke_remote_parser=lambda request: ParsedArtifact(
                    document_id=uuid4(),
                    pages=[ParsedPage(page_number=1, text="remote", blocks=[])],
                    tables=[],
                    provenance=ParserProvenance(
                        parser_backend="remote-api",
                        parser_version="1.0",
                        profile="remote-api",
                    ),
                )
            ),
            "remote-api",
            "remote-api",
        )

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("PARSER_PROFILE", "remote-api")
        reloaded_main = _reload_app_module()
        monkeypatch.setattr(reloaded_main, "build_document_parser", lambda settings: factory_result)

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50004)):
                ocr_result = reloaded_main.app.state.dispatcher._ocr_service.inspect(
                    request=ParseRequest(
                        document_id=str(uuid4()),
                        object_key="documents/remote.txt",
                        content_type="text/plain",
                        profile="remote-api",
                        parser_backend="remote-api",
                    ),
                    artifact=ParsedArtifact(
                        document_id=uuid4(),
                        pages=[ParsedPage(page_number=1, text="", blocks=[])],
                        tables=[],
                        provenance=ParserProvenance(
                            parser_backend="remote-api",
                            parser_version="1.0",
                            profile="remote-api",
                        ),
                    ),
                )
                assert ocr_result.provider == "remote-api"
                assert ocr_result.engine == "remote-service"
                assert ocr_result.status == "unverified"
        finally:
            session_factory.configure(bind=None)


def test_app_startup_succeeds_for_seaweedfs_with_local_docling_runtime_via_env(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup-seaweedfs-env.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("STORAGE_BACKEND", "seaweedfs")
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://seaweedfs:8333")
        monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
        monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
        monkeypatch.setenv("PARSER_BACKEND", "docling")
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50003)):
                assert hasattr(reloaded_main.app.state, "dispatcher")
                assert reloaded_main.app.state.dispatcher._storage is not None
        finally:
            session_factory.configure(bind=None)


def test_startup_uses_in_process_dispatcher_by_default(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'default-backend.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50010)):
                assert reloaded_main.app.state.dispatcher.__class__.__name__ == "InProcessDispatcher"
        finally:
            session_factory.configure(bind=None)


def test_startup_fails_when_temporal_backend_selected_without_host_port(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'temporal-no-config.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("WORKFLOW_BACKEND", "temporal")
        # Ensure no temporal_host_port is set
        monkeypatch.delenv("TEMPORAL_HOST_PORT", raising=False)
        reloaded_main = _reload_app_module()

        try:
            with pytest.raises(RuntimeError, match="temporal_host_port"):
                with TestClient(reloaded_main.app, client=("127.0.0.1", 50011)):
                    pass
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
