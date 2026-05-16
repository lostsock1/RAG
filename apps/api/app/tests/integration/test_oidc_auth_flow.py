from __future__ import annotations

import importlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from time import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import jwt
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import get_settings
from app.core.oidc import OidcTokenVerifier, get_oidc_token_verifier
from app.db.base import session_factory
from app.db.models.acl import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.document import Document
from app.db.models.group import Group, UserGroup
from app.db.models.tenant import Tenant
from app.db.models.user import User
import app.main as main_module


TEST_KEY_ID = "oidc-test-key"
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCxp1nXACYeFqQK
pJiQBgqGG2WQQW7hr9HEiKVS+A/wjXIqnUhtSWJhi8OVTFtnFn7UlHq7f7cDsFPv
cQTURjz5BN8jRJsP0gfNTAAXNrsTaY4Q4JTd561kuNI1els6PN6XGSE/oz9tlnYZ
jkHl/50mT86UtzBcOh8KwqGeT55LtOrjkRHOejbHecZkVak6/l5HAlUrfFDQUJiO
9w1OgvQ+sSiwqJ6NCz3Zcdxerl8O5ks64IBkpBmReQmobucBUeFsLf+rfaZBostZ
XE6No3lcUc738AQwvSUvuRIOamnO5ruDo+P6797JPo8qMNv1v4Td+6652jbjLLcL
0t2J6QLvAgMBAAECggEAMZYQ/PJlMUvHgNL9ZGHTSShXemLRJLxS9CTh5F0p8c5B
OgTJpPtxMuH0dvUnpAgC4aoJ8dDNkAGFBBXLL8blGOqTr7/j+g/5LoPSmKglol75
kNtmoeObIbx2rAeZdBFuXcVdYupZd2iiUTLEUQK+ZeWrtxXEsVFlvbairtHxUJbZ
P0e0w+Ex/KqcE+blWVD5wXbRnNYFDtNJotEQR4Gbd116KinJW+1vKGybJRDkYN5X
Zz7r6A58zsm/NRpebnNXPhcSiyYpmsWGbDXh3tCQPTwhw7v199EjNbdbKktLzZZz
BFsOcOcp9XzlfXMM0NnygeDLTQCEXnUaFDHtsRcTJQKBgQDdtb32gkPVowHgZvdF
F2JdGZBjso/+a9bLpvwx68ObA2aXndeu9uYpb7KsQR3QKajO6Z1LaYJRS/88Es5l
8P5fyoUyMCeJ5m5NpR7koT1FNZn8MnTZQIziRU20wFCzCz8WhRIrr0cCkDUMVcIl
FQ+Tj44GNXpzDbZObnWOP9xgRQKBgQDNIUWeVj2BMxIRmrg9xr/Sw7v5hjICriO9
aZcLb5ildGelwYAA7E6H+ifRtEDUnvZRdtAjt/yCUIKK+nHJ/HpN5MYpcg/acRAo
ZTpa0f3xEB5Ftm79SlBH+EmN/3bTttM5DiFi7YPcIv9SuY4NUWeekk5SRuW+/fMt
yIuc9c3LowKBgBBNc9lzfK9x3Ap3J8mBza7Q2WgrUiFAJrw03CiDkI+OcXXGmnx4
FTaIyxeVdi6/UXVdgj5wVK/LqcnuDBU84keC6cZl+hJOyl+VO69OF+ZF6bu8rhDn
iTR+KheXaJexxQLP6CUkL1GF7xCoIa1+XfXYwXW9avKY2IXt42EBWyANAoGAHeQx
TudmQwN8KJCRNH9XyJC5PZ0ugHF7x8gxOHtklQenauINkxTcRLhRQR+xKsqXPjvA
DNRsuVieDT59gl+GOv+RWMzEPqKnJhvKKx3akVw17Rauib5ggHxPy59kY2mK0g+b
Ed1mj5eR+S4M4yfvn43WV+r446IB47QLlC3FdV0CgYEA227YlksqEEJfXZnbGR05
BSI0z4/TnV2A0h8BCLvlX1LRWUak+01s9j6ZVUVGAS+OBAsnF8R+Za73sfVTe8tY
AtNyOMo9BZyHNCHP+aCMGc6Rj2xR/ezvQkhKFUQ00CjKTDImWhMttF9/EhQvraRo
vBbYxW4gP7l92Hx2I35ffSI=
-----END PRIVATE KEY-----"""
TEST_PUBLIC_JWK = json.loads(
    '{"kty": "RSA", "key_ops": ["verify"], "n": "sadZ1wAmHhakCqSYkAYKhhtlkEFu4a_RxIilUvgP8I1yKp1IbUliYYvDlUxbZxZ-1JR6u3-3A7BT73EE1EY8-QTfI0SbD9IHzUwAFza7E2mOEOCU3eetZLjSNXpbOjzelxkhP6M_bZZ2GY5B5f-dJk_OlLcwXDofCsKhnk-eS7Tq45ERzno2x3nGZFWpOv5eRwJVK3xQ0FCYjvcNToL0PrEosKiejQs92XHcXq5fDuZLOuCAZKQZkXkJqG7nAVHhbC3_q32mQaLLWVxOjaN5XFHO9_AEML0lL7kSDmppzua7g6Pj-u_eyT6PKjDb9b-E3fuuudo24yy3C9LdiekC7w", "e": "AQAB"}'
)


def _reload_app_module() -> object:
    get_settings.cache_clear()
    return importlib.reload(main_module)


def issue_test_token(
    *,
    sub: str,
    tenant_id: str,
    groups: list[str],
    roles: list[str],
    scopes: list[str],
    issuer: str = "http://localhost:8080/realms/uber-rag",
    audience: str = "uber-rag-api",
    kid: str = TEST_KEY_ID,
    exp: int | None = None,
) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "tenant_id": tenant_id,
            "groups": groups,
            "realm_access": {"roles": roles},
            "scope": " ".join(scopes),
            "iss": issuer,
            "aud": audience,
            **({"exp": exp} if exp is not None else {"exp": int(time()) + 300}),
        },
        TEST_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _seed_runtime_document(*, tmp_dir: str, slug: str) -> tuple[str, object, object, object, object]:
    tenant_id = uuid4()
    user_id = uuid4()
    group_id = uuid4()
    database_url = f"sqlite:///{Path(tmp_dir) / f'{slug}.db'}"
    engine = create_engine(database_url)
    alembic_ini_path = Path("infra/migrations/alembic.ini")
    config = Config(str(alembic_ini_path))
    config.set_main_option("sqlalchemy.url", database_url)

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session_factory.configure(bind=engine)
    with session_factory() as session:
        session.add(Tenant(id=tenant_id, name="Tenant", slug=f"{slug}-tenant"))
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{slug}@example.com",
                display_name="OIDC User",
                roles=["editor"],
            )
        )
        document = Document(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            title="OIDC Visible",
            source_type="loose_document",
            source_hash=f"{slug}-hash",
            file_name=f"{slug}.txt",
            file_size_bytes=1,
            object_key=f"documents/{slug}.txt",
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

    return database_url, engine, tenant_id, user_id, group_id


def _seed_runtime_document_with_named_group(*, tmp_dir: str, slug: str, group_name: str) -> tuple[str, object, object, object, object]:
    tenant_id = uuid4()
    user_id = uuid4()
    group_id = uuid4()
    database_url = f"sqlite:///{Path(tmp_dir) / f'{slug}.db'}"
    engine = create_engine(database_url)
    alembic_ini_path = Path("infra/migrations/alembic.ini")
    config = Config(str(alembic_ini_path))
    config.set_main_option("sqlalchemy.url", database_url)

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    session_factory.configure(bind=engine)
    with session_factory() as session:
        session.add(Tenant(id=tenant_id, name="Tenant", slug=f"{slug}-tenant"))
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{slug}@example.com",
                display_name="OIDC User",
                roles=["editor"],
            )
        )
        session.add(Group(id=group_id, tenant_id=tenant_id, name=group_name))
        session.add(UserGroup(user_id=user_id, group_id=group_id))
        document = Document(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            title="OIDC Named Group Visible",
            source_type="loose_document",
            source_hash=f"{slug}-hash",
            file_name=f"{slug}.txt",
            file_size_bytes=1,
            object_key=f"documents/{slug}.txt",
            ingestion_status="uploaded",
        )
        session.add(document)
        session.flush()
        acl_grant = AclGrant(
            document_id=document.id,
            owner_user_id=user_id,
            tenant_id=tenant_id,
            visibility="group",
            sensitivity="internal",
        )
        session.add(acl_grant)
        session.flush()
        session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=user_id))
        session.add(AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=group_id))
        session.commit()

    return database_url, engine, tenant_id, user_id, group_id


def _configure_oidc_runtime(monkeypatch, *, database_url: str, storage_dir: Path) -> object:
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("OIDC_ISSUER_URL", "http://localhost:8080/realms/uber-rag")
    monkeypatch.setenv("OIDC_AUDIENCE", "uber-rag-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs")
    monkeypatch.setattr(OidcTokenVerifier, "_fetch_jwks", lambda self: {"keys": [dict(TEST_PUBLIC_JWK, kid=TEST_KEY_ID)]})
    return _reload_app_module()


class _JwksHandler(BaseHTTPRequestHandler):
    jwks_payload = {"keys": [dict(TEST_PUBLIC_JWK, kid=TEST_KEY_ID)]}
    request_count = 0

    def do_GET(self):  # noqa: N802
        type(self).request_count += 1
        body = json.dumps(self.jwks_payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def _start_jwks_server() -> tuple[ThreadingHTTPServer, Thread, str]:
    _JwksHandler.request_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JwksHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/jwks.json"
    return server, thread, url


def test_oidc_token_allows_document_list(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, group_id = _seed_runtime_document(tmp_dir=tmp_dir, slug="oidc-auth")
        reloaded_main = _configure_oidc_runtime(monkeypatch, database_url=database_url, storage_dir=storage_dir)
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[str(group_id)],
            roles=["editor"],
            scopes=["documents:read"],
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200
            assert [item["title"] for item in response.json()["items"]] == ["OIDC Visible"]
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_group_name_claim_allows_document_list(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, _ = _seed_runtime_document_with_named_group(
            tmp_dir=tmp_dir,
            slug="oidc-group-name",
            group_name="alpha",
        )
        reloaded_main = _configure_oidc_runtime(monkeypatch, database_url=database_url, storage_dir=storage_dir)
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=["alpha"],
            roles=["editor"],
            scopes=["documents:read"],
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200
            assert [item["title"] for item in response.json()["items"]] == ["OIDC Named Group Visible"]
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_token_missing_scope_gets_403(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, _ = _seed_runtime_document(
            tmp_dir=tmp_dir,
            slug="oidc-missing-scope",
        )
        reloaded_main = _configure_oidc_runtime(monkeypatch, database_url=database_url, storage_dir=storage_dir)
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[],
            roles=["editor"],
            scopes=[],
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 403
            assert response.json() == {
                "detail": "Missing required scope: documents:read. Request a token with the required scope and try again.",
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_wrong_issuer_gets_401(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, _ = _seed_runtime_document(
            tmp_dir=tmp_dir,
            slug="oidc-wrong-issuer",
        )
        reloaded_main = _configure_oidc_runtime(monkeypatch, database_url=database_url, storage_dir=storage_dir)
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[],
            roles=["editor"],
            scopes=["documents:read"],
            issuer="http://wrong-issuer",
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 401
            assert response.json() == {
                "detail": "OIDC token claims are invalid for this API. Confirm the token includes sub, tenant_id, groups, roles, and scope claims expected by the server.",
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_unknown_kid_gets_401(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, _ = _seed_runtime_document(
            tmp_dir=tmp_dir,
            slug="oidc-unknown-kid",
        )
        reloaded_main = _configure_oidc_runtime(monkeypatch, database_url=database_url, storage_dir=storage_dir)
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[],
            roles=["editor"],
            scopes=["documents:read"],
            kid="missing-key",
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 401
            assert response.json() == {
                "detail": "OIDC token claims are invalid for this API. Confirm the token includes sub, tenant_id, groups, roles, and scope claims expected by the server.",
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_token_missing_exp_gets_401(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, _ = _seed_runtime_document(
            tmp_dir=tmp_dir,
            slug="oidc-missing-exp",
        )
        reloaded_main = _configure_oidc_runtime(monkeypatch, database_url=database_url, storage_dir=storage_dir)
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[],
            roles=["editor"],
            scopes=["documents:read"],
            exp=None,
        )
        payload = jwt.decode(token, options={"verify_signature": False})
        payload.pop("exp", None)
        token = jwt.encode(payload, TEST_PRIVATE_KEY, algorithm="RS256", headers={"kid": TEST_KEY_ID})

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 401
            assert response.json() == {
                "detail": "OIDC token claims are invalid for this API. Confirm the token includes sub, tenant_id, groups, roles, and scope claims expected by the server.",
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_missing_jwks_url_gets_503(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, _ = _seed_runtime_document(
            tmp_dir=tmp_dir,
            slug="oidc-missing-jwks-url",
        )
        monkeypatch.setenv("AUTH_MODE", "oidc")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("OIDC_ISSUER_URL", "http://localhost:8080/realms/uber-rag")
        monkeypatch.setenv("OIDC_AUDIENCE", "uber-rag-api")
        monkeypatch.delenv("OIDC_JWKS_URL", raising=False)
        reloaded_main = _reload_app_module()
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[],
            roles=["editor"],
            scopes=["documents:read"],
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 503
            assert response.json() == {
                "detail": "OIDC authentication is enabled but not fully configured. Set OIDC_ISSUER_URL, OIDC_AUDIENCE, and OIDC_JWKS_URL before calling protected endpoints.",
            }
        finally:
            session_factory.configure(bind=None)
            engine.dispose()
            reloaded_main.app.dependency_overrides.clear()


def test_oidc_token_allows_document_list_via_real_jwks_http_fetch(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir) / "storage"
        database_url, engine, tenant_id, user_id, group_id = _seed_runtime_document(tmp_dir=tmp_dir, slug="oidc-http-jwks")
        server, thread, jwks_url = _start_jwks_server()
        monkeypatch.setenv("AUTH_MODE", "oidc")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("OIDC_ISSUER_URL", "http://localhost:8080/realms/uber-rag")
        monkeypatch.setenv("OIDC_AUDIENCE", "uber-rag-api")
        monkeypatch.setenv("OIDC_JWKS_URL", jwks_url)
        get_oidc_token_verifier.cache_clear()
        reloaded_main = _reload_app_module()
        token = issue_test_token(
            sub=str(user_id),
            tenant_id=str(tenant_id),
            groups=[str(group_id)],
            roles=["editor"],
            scopes=["documents:read"],
        )

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50000)) as client:
                response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )
                second_response = client.get(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert response.status_code == 200
            assert second_response.status_code == 200
            assert [item["title"] for item in response.json()["items"]] == ["OIDC Visible"]
            assert _JwksHandler.request_count == 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            session_factory.configure(bind=None)
            engine.dispose()
            get_oidc_token_verifier.cache_clear()
            reloaded_main.app.dependency_overrides.clear()
