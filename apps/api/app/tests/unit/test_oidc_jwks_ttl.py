"""P0-4: JWKS TTL cache and kid-miss expiry tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings, get_settings
from app.core.oidc import OidcTokenVerifier, select_jwk_by_kid


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
async def test_jwks_cache_is_used_within_ttl(monkeypatch) -> None:
    first = {"keys": [{"kid": "key-1", "kty": "RSA", "n": "a", "e": "AQAB"}]}
    fetch_count = 0

    async def fake_fetch(self):
        nonlocal fetch_count
        fetch_count += 1
        return first

    verifier = OidcTokenVerifier()
    monkeypatch.setattr(OidcTokenVerifier, "_fetch_jwks", fake_fetch)

    # First call fetches
    key1 = await verifier._resolve_jwk_for_kid("key-1")
    assert key1["kid"] == "key-1"
    assert fetch_count == 1

    # Second call within TTL uses cache
    key2 = await verifier._resolve_jwk_for_kid("key-1")
    assert key2["kid"] == "key-1"
    assert fetch_count == 1  # no additional fetch


@pytest.mark.anyio
async def test_jwks_cache_expires_on_ttl(monkeypatch) -> None:
    first = {"keys": [{"kid": "key-1", "kty": "RSA", "n": "a", "e": "AQAB"}]}
    second = {"keys": [{"kid": "key-1", "kty": "RSA", "n": "b", "e": "AQAB"}]}
    responses = iter([first, second])
    fetch_count = 0

    async def fake_fetch(self):
        nonlocal fetch_count
        fetch_count += 1
        return next(responses)

    verifier = OidcTokenVerifier()
    monkeypatch.setattr(OidcTokenVerifier, "_fetch_jwks", fake_fetch)

    # First fetch
    await verifier._resolve_jwk_for_kid("key-1")
    assert fetch_count == 1

    # Expire the cache. `_is_cache_expired` compares time.monotonic() to
    # `_jwks_fetched_at`, and `monotonic()` returns process-relative seconds,
    # not Unix epoch. Setting `_jwks_fetched_at = 0.0` only "expires" if the
    # process has been running longer than the TTL — true on long-lived dev
    # machines, false on fresh CI runners (process is seconds old).
    # Force expiry by setting fetched_at one full TTL window in the past
    # of monotonic-now.
    import time
    from app.core.config import get_settings
    verifier._jwks_fetched_at = time.monotonic() - get_settings().oidc_jwks_ttl_seconds - 1.0

    # Second call should re-fetch
    key = await verifier._resolve_jwk_for_kid("key-1")
    assert fetch_count == 2
    assert key["n"] == "b"  # from second fetch


@pytest.mark.anyio
async def test_jwks_cache_refreshes_on_kid_miss(monkeypatch) -> None:
    first = {"keys": [{"kid": "old-key", "kty": "RSA", "n": "a", "e": "AQAB"}]}
    second = {"keys": [{"kid": "new-key", "kty": "RSA", "n": "b", "e": "AQAB"}]}
    responses = iter([first, second])

    async def fake_fetch(self):
        return next(responses)

    verifier = OidcTokenVerifier()
    monkeypatch.setattr(OidcTokenVerifier, "_fetch_jwks", fake_fetch)

    key = await verifier._resolve_jwk_for_kid("new-key")
    assert key["kid"] == "new-key"


def test_oidc_clock_skew_settings_exist() -> None:
    settings = Settings(oidc_clock_skew_seconds=60, oidc_jwks_ttl_seconds=300)
    assert settings.oidc_clock_skew_seconds == 60
    assert settings.oidc_jwks_ttl_seconds == 300


def test_docs_truthfully_describe_jwks_backed_auth_closeout() -> None:
    readme_text = Path("README.md").read_text()
    project_state_text = Path("docs/uber-rag/PROJECT_STATE.md").read_text()
    tasks_text = Path("docs/uber-rag/TASKS.md").read_text()

    assert "OIDC_JWKS_URL" in readme_text
    assert "JWKS-backed" in project_state_text
    assert "JWKS-backed" in tasks_text
