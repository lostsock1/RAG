from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.citations import ResolveCitationsRequest, ResolveCitationsResponse
from app.schemas.search import SearchRequest
from app.services.citation_resolver import CitationResolver
from app.services.retrieval.search_service import SearchService

router = APIRouter()


@router.post("/resolve", response_model=ResolveCitationsResponse)
def resolve_citations_route(
    request: Request,
    payload: ResolveCitationsRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> ResolveCitationsResponse:
    retriever = getattr(request.app.state, "search_retriever", None)
    if retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search retrieval is not configured yet. Configure a search retriever before resolving citations.",
        )

    search_service = SearchService(retriever=retriever)
    search_response = search_service.search(
        context=context,
        payload=SearchRequest(
            query=" ".join(payload.citations),
            top_k=max(len(payload.citations), 1),
        ),
    )
    return CitationResolver().resolve(citation_ids=payload.citations, hits=search_response.items)
