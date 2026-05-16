from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.repositories.documents import get_document_acl, update_document_acl
from app.schemas.acl import DocumentAclResponse, DocumentAclUpdateRequest

router = APIRouter()


@router.get("/{document_id}/acl", response_model=DocumentAclResponse)
def get_document_acl_route(
    document_id: UUID,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> DocumentAclResponse:
    acl = get_document_acl(
        document_id=document_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        roles=context.roles,
    )
    if acl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document ACL not found for this user.",
        )

    return DocumentAclResponse.model_validate(acl)


@router.put("/{document_id}/acl", response_model=DocumentAclResponse)
def update_document_acl_route(
    document_id: UUID,
    payload: DocumentAclUpdateRequest,
    context: RequestContext = Depends(require_scopes(["documents:write"])),
) -> DocumentAclResponse:
    acl = update_document_acl(
        document_id=document_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        roles=context.roles,
        visibility=payload.visibility,
        allowed_user_ids=payload.allowed_user_ids,
        allowed_group_ids=payload.allowed_group_ids,
        sensitivity=payload.sensitivity,
        expires_at=payload.expires_at,
    )
    if acl is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document ACL not found for this user.",
        )

    return DocumentAclResponse.model_validate(acl)
