from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from ipaddress import ip_address
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.oidc import get_oidc_token_verifier
from app.core.request_context import RequestContext

_log = logging.getLogger(__name__)


class InvalidIdentityError(ValueError):
    """Raised when a tenant_id, user_id, or group_id is not a valid UUID."""


def _validate_uuid(value: str, field_name: str) -> str:
    """Validate that *value* is a well-formed UUID string.

    Returns the canonical string form on success, raises InvalidIdentityError otherwise.
    """
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise InvalidIdentityError(f"{field_name} is not a valid UUID: {value!r}")


def _parse_csv_header(value: str | None) -> list[str]:
    if value is None:
        return []

    return [item.strip() for item in value.split(",") if item.strip()]


def _is_loopback_client_host(host: str | None) -> bool:
    if host is None:
        return False

    if host in {"localhost", "127.0.0.1", "::1"}:
        return True

    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _get_nested_claim(claims: Mapping[str, Any], claim_path: str) -> Any:
    value: Any = claims
    for part in claim_path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def assert_dev_auth_bind_is_loopback(server_host: str) -> None:
    """Raise RuntimeError if AUTH_MODE=dev and the bind address is not loopback.

    Call this at app factory time to prevent dev-auth from being accidentally
    exposed behind a public reverse proxy.
    """
    if not _is_loopback_client_host(server_host):
        raise RuntimeError(
            f"AUTH_MODE=dev is not allowed when the server bind address is '{server_host}'. "
            "Dev authentication is only safe on loopback (127.0.0.1 / ::1 / localhost). "
            "Set SERVER_HOST=127.0.0.1 or switch to AUTH_MODE=oidc for non-loopback deployments."
        )


def build_request_context_from_claims(claims: Mapping[str, Any]) -> RequestContext:
    settings = get_settings()
    raw_groups = _get_nested_claim(claims, settings.oidc_groups_claim) if settings.oidc_groups_claim else claims.get("groups")
    raw_roles = _get_nested_claim(claims, settings.oidc_roles_claim) if settings.oidc_roles_claim else _get_nested_claim(claims, "realm_access.roles")
    raw_scopes = _get_nested_claim(claims, settings.oidc_scopes_claim) if settings.oidc_scopes_claim else claims.get("scope")
    scope_claim_present = raw_scopes is not None

    if isinstance(raw_scopes, list):
        scopes = [str(scope) for scope in raw_scopes if str(scope).strip()]
    elif raw_scopes is not None:
        scopes = [scope for scope in str(raw_scopes).split(" ") if scope]
    else:
        scopes = []

    groups = [str(group) for group in (raw_groups or [])]
    roles = [str(role) for role in (raw_roles or [])]

    if not scopes and not scope_claim_present:
        inferred_scopes: set[str] = set()
        if "editor" in roles or "admin" in roles:
            inferred_scopes.update({"documents:read", "documents:write"})
        scopes = sorted(inferred_scopes)

    return RequestContext(
        tenant_id=_validate_uuid(claims["tenant_id"], "tenant_id"),
        user_id=_validate_uuid(claims["sub"], "user_id"),
        group_ids=groups,
        roles=roles,
        scopes=scopes,
    )


async def get_request_context(
    request: Request,
    authorization: str | None = Header(default=None),
    x_dev_auth_tenant_id: str | None = Header(default=None),
    x_dev_auth_user_id: str | None = Header(default=None),
    x_dev_auth_groups: str | None = Header(default=None),
    x_dev_auth_roles: str | None = Header(default=None),
    x_dev_auth_scopes: str | None = Header(default=None),
) -> RequestContext:
    settings = get_settings()

    if settings.auth_mode == "oidc":
        if not settings.oidc_issuer_url or not settings.oidc_audience or not settings.oidc_jwks_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "OIDC authentication is enabled but not fully configured. Set OIDC_ISSUER_URL, "
                    "OIDC_AUDIENCE, and OIDC_JWKS_URL before calling protected endpoints."
                ),
            )

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
            )

        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
            )

        try:
            claims = await get_oidc_token_verifier().verify_bearer_token(token)
            return build_request_context_from_claims(claims)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "OIDC token claims are invalid for this API. Confirm the token includes sub, tenant_id, "
                    "groups, roles, and scope claims expected by the server."
                ),
            ) from exc

    if settings.auth_mode == "dev":
        client_host = request.client.host if request.client else None
        if not _is_loopback_client_host(client_host):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Development authentication is only available from loopback clients. "
                    "Use localhost for local development or configure production authentication."
                ),
            )

        # Belt-and-suspenders: reject if a forwarding header is present.
        # A reverse proxy that loopbacks to 127.0.0.1 would pass the host check
        # above but still expose dev-auth to the public internet.
        if request.headers.get("X-Forwarded-For") is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Development authentication is not available when X-Forwarded-For is present. "
                    "Do not run AUTH_MODE=dev behind a reverse proxy."
                ),
            )

        _log.warning(
            "DEV AUTH: request from %s — development authentication is active. "
            "Do NOT use AUTH_MODE=dev in production.",
            client_host,
        )

        if not x_dev_auth_tenant_id or not x_dev_auth_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Development authentication requires X-Dev-Auth-Tenant-Id and "
                    "X-Dev-Auth-User-Id headers. Add those headers or disable the protected route call."
                ),
            )

        try:
            validated_tenant_id = _validate_uuid(x_dev_auth_tenant_id, "tenant_id")
            validated_user_id = _validate_uuid(x_dev_auth_user_id, "user_id")
            raw_groups = _parse_csv_header(x_dev_auth_groups)
            validated_groups = [_validate_uuid(g, "group_id") for g in raw_groups]
        except InvalidIdentityError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return RequestContext(
            tenant_id=validated_tenant_id,
            user_id=validated_user_id,
            group_ids=validated_groups,
            roles=_parse_csv_header(x_dev_auth_roles),
            scopes=_parse_csv_header(x_dev_auth_scopes),
        )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Authentication is not configured. Set AUTH_MODE=dev for local development or configure "
            "production authentication before calling protected endpoints."
        ),
    )


def require_scopes(required_scopes: list[str]) -> Callable[[RequestContext], RequestContext]:
    def dependency(context: RequestContext = Depends(get_request_context)) -> RequestContext:
        missing_scopes = [scope for scope in required_scopes if scope not in context.scopes]
        if missing_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Missing required scope: "
                    f"{', '.join(missing_scopes)}. Request a token with the required scope and try again."
                ),
            )

        return context

    return dependency
