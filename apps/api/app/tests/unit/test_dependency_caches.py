from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.caches import reset_dependency_caches
from app.core.config import get_settings
from app.core.oidc import get_oidc_token_verifier


def test_reset_dependency_caches_clears_settings_and_verifier():
    """P2-2: one helper clears both process-wide lru_caches."""
    settings_before = get_settings()
    verifier_before = get_oidc_token_verifier()
    assert get_settings() is settings_before
    assert get_oidc_token_verifier() is verifier_before

    reset_dependency_caches()

    assert get_settings() is not settings_before
    assert get_oidc_token_verifier() is not verifier_before


def test_reset_dependency_caches_fixture_is_wired(reset_dependency_caches):
    """P2-2: the conftest fixture resolves and yields a usable test context."""
    assert get_settings() is get_settings()
