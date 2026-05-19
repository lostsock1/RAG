from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.search import SearchRequest, SearchResponse
from app.services.retrieval.search_service import SearchService

router = APIRouter()


@router.post('', response_model=SearchResponse)
def search_route(
    request: Request,
    payload: SearchRequest,
    context: RequestContext = Depends(require_scopes(['documents:read'])),
) -> SearchResponse:
    retriever = getattr(request.app.state, 'search_retriever', None)
    if retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Search retrieval is not configured yet. Configure a search retriever before using /search.',
        )
    return SearchService(retriever=retriever).search(context=context, payload=payload)
