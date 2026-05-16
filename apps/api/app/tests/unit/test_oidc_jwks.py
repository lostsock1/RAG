from pathlib import Path
import sys


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



def test_verifier_refreshes_jwks_when_kid_missing(monkeypatch) -> None:
    first = {"keys": [{"kid": "old-key", "kty": "RSA", "n": "a", "e": "AQAB"}]}
    second = {"keys": [{"kid": "new-key", "kty": "RSA", "n": "b", "e": "AQAB"}]}
    calls = iter([first, second])

    verifier = OidcTokenVerifier()
    monkeypatch.setattr(verifier, "_fetch_jwks", lambda: next(calls))

    key = verifier._resolve_jwk_for_kid("new-key")

    assert key["kid"] == "new-key"


def test_docs_truthfully_describe_jwks_backed_auth_closeout() -> None:
    readme_text = Path("README.md").read_text()
    project_state_text = Path("docs/uber-rag/PROJECT_STATE.md").read_text()
    tasks_text = Path("docs/uber-rag/TASKS.md").read_text()

    assert "OIDC_JWKS_URL" in readme_text
    assert "JWKS-backed" in project_state_text
    assert "JWKS-backed" in tasks_text
