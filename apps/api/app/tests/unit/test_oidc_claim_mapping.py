from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.core.oidc import decode_and_validate_claims
from app.core.request_context import RequestContext
from app.core.security import build_request_context_from_claims


def test_oidc_settings_exist() -> None:
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer_url="http://localhost:8080/realms/uber-rag",
        oidc_audience="uber-rag-api",
        oidc_client_id="uber-rag-api",
    )
    assert settings.auth_mode == "oidc"
    assert settings.oidc_issuer_url == "http://localhost:8080/realms/uber-rag"
    assert settings.oidc_audience == "uber-rag-api"


def test_decode_and_validate_token_rejects_wrong_audience() -> None:
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "iss": "http://localhost:8080/realms/uber-rag",
        "aud": "wrong-audience",
        "scope": "documents:read",
    }

    with pytest.raises(ValueError, match="audience"):
        decode_and_validate_claims(
            claims=claims,
            issuer="http://localhost:8080/realms/uber-rag",
            audience="uber-rag-api",
        )


def test_build_request_context_from_keycloak_claims() -> None:
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "tenant-1",
        "groups": ["group-a", "group-b"],
        "realm_access": {"roles": ["editor"]},
        "scope": "documents:read documents:write",
    }

    context = build_request_context_from_claims(claims)

    assert isinstance(context, RequestContext)
    assert context.user_id == "11111111-1111-1111-1111-111111111111"
    assert context.group_ids == ["group-a", "group-b"]
    assert context.scopes == ["documents:read", "documents:write"]
