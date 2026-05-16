from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

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

    def verify_bearer_token(self, token: str) -> dict[str, Any]:
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

        jwk = self._resolve_jwk_for_kid(str(kid))

        try:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=[ACCEPTED_OIDC_SIGNING_ALGORITHM],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer_url,
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

    def _fetch_jwks(self) -> dict[str, Any]:
        settings = get_settings()
        if not settings.oidc_jwks_url:
            raise ValueError("OIDC JWKS URL must be configured")

        try:
            with urlopen(settings.oidc_jwks_url, timeout=OIDC_JWKS_FETCH_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
        except URLError as exc:
            raise ValueError("OIDC JWKS fetch failed") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("OIDC JWKS response was not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("OIDC JWKS response must be a JSON object")

        return payload

    def _resolve_jwk_for_kid(self, kid: str) -> dict[str, Any]:
        if self._jwks_cache is None:
            self._jwks_cache = self._fetch_jwks()

        try:
            return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)
        except ValueError:
            self._jwks_cache = self._fetch_jwks()
            return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)


@lru_cache(maxsize=1)
def get_oidc_token_verifier() -> OidcTokenVerifier:
    return OidcTokenVerifier()
