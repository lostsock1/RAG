from __future__ import annotations

import json
import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError

from app.core.config import get_settings


ACCEPTED_OIDC_SIGNING_ALGORITHM = "RS256"
OIDC_JWKS_FETCH_TIMEOUT_SECONDS = 5


def decode_and_validate_claims(*, claims: Mapping[str, Any], issuer: str, audience: str) -> dict[str, Any]:
    if claims.get("iss") != issuer:
        raise ValueError("issuer mismatch")

    aud = claims.get("aud")
    if aud != audience and not (isinstance(aud, list) and audience in aud):
        raise ValueError("audience mismatch")

    if "sub" not in claims:
        raise ValueError("subject missing")

    return dict(claims)


def select_jwk_by_kid(*, jwks: dict[str, Any], kid: str) -> dict[str, Any]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return dict(key)

    raise ValueError(f"No JWKS key found for kid={kid}")


class OidcTokenVerifier:
    def __init__(self) -> None:
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

    async def verify_bearer_token(self, token: str) -> dict[str, Any]:
        settings = get_settings()
        if not settings.oidc_issuer_url or not settings.oidc_audience:
            raise ValueError("OIDC issuer and audience must be configured")
        if not settings.oidc_jwks_url:
            raise ValueError("OIDC JWKS URL must be configured")

        header = self._get_token_header(token)
        algorithm = header.get("alg")
        if algorithm != ACCEPTED_OIDC_SIGNING_ALGORITHM:
            raise ValueError("token algorithm is invalid")

        kid = header.get("kid")
        if not kid:
            raise ValueError("token kid is missing")

        jwk = await self._resolve_jwk_for_kid(str(kid))

        try:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=[ACCEPTED_OIDC_SIGNING_ALGORITHM],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer_url,
                leeway=settings.oidc_clock_skew_seconds,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except InvalidTokenError as exc:
            raise ValueError("token verification failed") from exc

        return decode_and_validate_claims(
            claims=claims,
            issuer=settings.oidc_issuer_url,
            audience=settings.oidc_audience,
        )

    def _get_token_header(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise ValueError("token header is invalid") from exc

        if not isinstance(header, dict):
            raise ValueError("token header is invalid")

        return header

    async def _fetch_jwks(self) -> dict[str, Any]:
        settings = get_settings()
        if not settings.oidc_jwks_url:
            raise ValueError("OIDC JWKS URL must be configured")

        try:
            async with httpx.AsyncClient(timeout=OIDC_JWKS_FETCH_TIMEOUT_SECONDS) as client:
                response = await client.get(settings.oidc_jwks_url)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ValueError("OIDC JWKS fetch failed") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("OIDC JWKS response was not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("OIDC JWKS response must be a JSON object")

        return payload

    def _is_cache_expired(self) -> bool:
        if self._jwks_cache is None:
            return True
        settings = get_settings()
        ttl = settings.oidc_jwks_ttl_seconds
        return (time.monotonic() - self._jwks_fetched_at) > ttl

    async def _resolve_jwk_for_kid(self, kid: str) -> dict[str, Any]:
        # Try cache first (if not expired)
        if self._jwks_cache is not None and not self._is_cache_expired():
            try:
                return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)
            except ValueError:
                pass  # kid miss — fall through to refresh

        # Fetch (or re-fetch on kid-miss)
        self._jwks_cache = await self._fetch_jwks()
        self._jwks_fetched_at = time.monotonic()

        try:
            return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)
        except ValueError:
            # One more attempt: re-fetch in case of key rotation
            self._jwks_cache = await self._fetch_jwks()
            self._jwks_fetched_at = time.monotonic()
            return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)


@lru_cache(maxsize=1)
def get_oidc_token_verifier() -> OidcTokenVerifier:
    return OidcTokenVerifier()
