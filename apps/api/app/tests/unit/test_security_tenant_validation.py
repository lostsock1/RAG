"""P0-3: tenant_id / user_id / group_id UUID validation.

Ensures that forged identity values (path-traversal, non-UUID, URL-encoded
slashes) are rejected before they reach the storage layer.
"""

from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.security import (
    InvalidIdentityError,
    _validate_uuid,
    build_request_context_from_claims,
)


# ---------------------------------------------------------------------------
# _validate_uuid unit tests
# ---------------------------------------------------------------------------

def test_validate_uuid_accepts_valid_uuid() -> None:
    valid = str(uuid4())
    assert _validate_uuid(valid, "tenant_id") == valid


def test_validate_uuid_rejects_path_traversal() -> None:
    with pytest.raises(InvalidIdentityError, match="tenant_id"):
        _validate_uuid("../etc", "tenant_id")


def test_validate_uuid_rejects_non_uuid_string() -> None:
    with pytest.raises(InvalidIdentityError, match="user_id"):
        _validate_uuid("not-a-uuid", "user_id")


def test_validate_uuid_rejects_url_encoded_slash() -> None:
    with pytest.raises(InvalidIdentityError, match="tenant_id"):
        _validate_uuid("%2F..%2Fetc", "tenant_id")


def test_validate_uuid_rejects_empty_string() -> None:
    with pytest.raises(InvalidIdentityError, match="tenant_id"):
        _validate_uuid("", "tenant_id")


# ---------------------------------------------------------------------------
# build_request_context_from_claims — OIDC path
# ---------------------------------------------------------------------------

def test_oidc_claims_reject_invalid_tenant_id() -> None:
    claims = {
        "sub": str(uuid4()),
        "tenant_id": "../etc",
        "groups": [],
        "realm_access": {"roles": ["editor"]},
        "scope": "documents:read",
    }
    with pytest.raises(InvalidIdentityError, match="tenant_id"):
        build_request_context_from_claims(claims)


def test_oidc_claims_reject_invalid_user_id() -> None:
    claims = {
        "sub": "not-a-uuid",
        "tenant_id": str(uuid4()),
        "groups": [],
        "realm_access": {"roles": ["editor"]},
        "scope": "documents:read",
    }
    with pytest.raises(InvalidIdentityError, match="user_id"):
        build_request_context_from_claims(claims)


def test_oidc_claims_accept_valid_uuids() -> None:
    tenant = str(uuid4())
    user = str(uuid4())
    group = str(uuid4())
    claims = {
        "sub": user,
        "tenant_id": tenant,
        "groups": [group],
        "realm_access": {"roles": ["editor"]},
        "scope": "documents:read",
    }
    ctx = build_request_context_from_claims(claims)
    assert ctx.tenant_id == tenant
    assert ctx.user_id == user
    assert ctx.group_ids == [group]


def test_oidc_claims_accept_non_uuid_group_names() -> None:
    """OIDC groups can be names (not UUIDs) — they are resolved later."""
    tenant = str(uuid4())
    user = str(uuid4())
    claims = {
        "sub": user,
        "tenant_id": tenant,
        "groups": ["alpha", "beta"],
        "realm_access": {"roles": ["editor"]},
        "scope": "documents:read",
    }
    ctx = build_request_context_from_claims(claims)
    assert ctx.group_ids == ["alpha", "beta"]
