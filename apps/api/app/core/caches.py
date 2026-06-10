from __future__ import annotations

from app.core.config import get_settings
from app.core.oidc import get_oidc_token_verifier


def reset_dependency_caches() -> None:
    """Clear process-wide lru_cache'd dependencies (Settings, OIDC verifier).

    Test-isolation helper: environment changes do not propagate into an
    already-cached ``Settings`` or ``OidcTokenVerifier`` instance, so tests
    that mutate env vars must clear both caches before and after running.
    """
    get_settings.cache_clear()
    get_oidc_token_verifier.cache_clear()
