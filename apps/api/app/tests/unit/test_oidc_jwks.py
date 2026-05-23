from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.core.oidc import OidcTokenVerifier, select_jwk_by_kid


def test_oidc_jwks_settings_can_be_configured() -> None:
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer_url="http://localhost:8080/realms/uber-rag",
        oidc_audience="uber-rag-api",
        oidc_jwks_url="http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs",
    )
    assert settings.oidc_jwks_url == "http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs"


def test_select_jwk_by_kid_returns_matching_key() -> None:
    jwks = {
        "keys": [
            {"kid": "key-a", "kty": "RSA", "n": "a", "e": "AQAB"},
            {"kid": "key-b", "kty": "RSA", "n": "b", "e": "AQAB"},
        ]
    }

    key = select_jwk_by_kid(jwks=jwks, kid="key-b")

    assert key["kid"] == "key-b"


@pytest.mark.anyio
async def test_verifier_refreshes_jwks_when_kid_missing(monkeypatch) -> None:
    first = {"keys": [{"kid": "old-key", "kty": "RSA", "n": "a", "e": "AQAB"}]}
    second = {"keys": [{"kid": "new-key", "kty": "RSA", "n": "b", "e": "AQAB"}]}
    calls = iter([first, second])

    async def fake_fetch(self):
        return next(calls)

    verifier = OidcTokenVerifier()
    monkeypatch.setattr(OidcTokenVerifier, "_fetch_jwks", fake_fetch)

    key = await verifier._resolve_jwk_for_kid("new-key")

    assert key["kid"] == "new-key"
