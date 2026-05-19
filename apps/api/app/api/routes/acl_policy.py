from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.repositories.acl_policy import (
    AclPolicyLockedError,
    configure_tenant_acl_policy,
    get_tenant_acl_policy,
)
from app.schemas.acl import (
    TenantAclBootstrapPolicyResponse,
    TenantAclBootstrapPolicyUpdateRequest,
)

router = APIRouter()


@router.get('/bootstrap-policy', response_model=TenantAclBootstrapPolicyResponse)
def get_acl_bootstrap_policy_route(
    context: RequestContext = Depends(require_scopes(['documents:read'])),
) -> TenantAclBootstrapPolicyResponse:
    try:
        policy = get_tenant_acl_policy(tenant_id=UUID(context.tenant_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='ACL bootstrap policy has not been configured for this tenant yet.',
        )

    return TenantAclBootstrapPolicyResponse.model_validate(policy)


@router.put('/bootstrap-policy', response_model=TenantAclBootstrapPolicyResponse)
def configure_acl_bootstrap_policy_route(
    payload: TenantAclBootstrapPolicyUpdateRequest,
    context: RequestContext = Depends(require_scopes(['documents:write'])),
) -> TenantAclBootstrapPolicyResponse:
    try:
        policy = configure_tenant_acl_policy(
            tenant_id=UUID(context.tenant_id),
            default_visibility_mode=payload.default_visibility_mode,
            visibility_display_names=payload.visibility_display_names,
            visibility_active_flags=payload.visibility_active_flags,
            sensitivity_display_names=payload.sensitivity_display_names,
            dimension_display_names=payload.dimension_display_names,
            dimension_active_flags=payload.dimension_active_flags,
        )
    except AclPolicyLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return TenantAclBootstrapPolicyResponse.model_validate(policy)
