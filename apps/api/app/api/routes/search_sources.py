from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.repositories.audit import write_audit_event
from app.repositories.search_sources import get_source_slice_by_chunk_id
from app.schemas.search import SearchSourceChunkResponse, SearchSourceResponse

router = APIRouter()

_NOT_FOUND_DETAIL = 'Search source was not found or you do not have access to it.'


@router.get('/sources/{chunk_id}', response_model=SearchSourceResponse)
def get_search_source_route(
    request: Request,
    chunk_id: str,
    context: RequestContext = Depends(require_scopes(['documents:read'])),
) -> SearchSourceResponse:
    context_window = max(int(getattr(request.app.state, 'search_source_context_window', 1)), 0)
    source_slice = get_source_slice_by_chunk_id(
        chunk_id=chunk_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        group_ids=context.group_ids,
        context_window=context_window,
    )
    if source_slice is None:
        write_audit_event(
            tenant_id=UUID(context.tenant_id),
            user_id=UUID(context.user_id),
            action='search.source.view.denied',
            resource_type='document',
            resource_id=None,
            details={
                'citation_id': chunk_id,
                'reason': 'not_found_or_denied',
            },
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    response = SearchSourceResponse(
        citation_id=chunk_id,
        document_id=str(source_slice['document_id']),
        document_title=str(source_slice['document_title']),
        source_type=str(source_slice['source_type']),
        focus_chunk_id=str(source_slice['chunk_id']),
        parent_chunk_id=source_slice.get('parent_chunk_id'),
        items=[SearchSourceChunkResponse.model_validate(item) for item in source_slice.get('items', [])],
    )

    write_audit_event(
        tenant_id=UUID(context.tenant_id),
        user_id=UUID(context.user_id),
        action='search.source.view',
        resource_type='document',
        resource_id=UUID(response.document_id),
        details={
            'citation_id': chunk_id,
            'returned_chunk_ids': [item.chunk_id for item in response.items],
            'focus_chunk_id': response.focus_chunk_id,
        },
    )

    return response
