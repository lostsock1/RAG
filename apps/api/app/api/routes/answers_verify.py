from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.context import BuildContextRequest
from app.schemas.search import SearchRequest
from app.schemas.verification import VerifyAnswerRequest, VerificationSummary
from app.services.answer_verifier import AnswerVerifier
from app.services.context_builder import DefaultContextBuilder
from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.search_service import SearchService

router = APIRouter()


@router.post("/verify", response_model=VerificationSummary)
def verify_answer_route(
    request: Request,
    payload: VerifyAnswerRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> VerificationSummary:
    retriever = getattr(request.app.state, "search_retriever", None)
    if retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search retrieval is not configured yet. Configure a search retriever before verifying answers.",
        )

    settings = request.app.state.settings
    search_service = SearchService(retriever=retriever)
    search_response = search_service.search(
        context=context,
        payload=SearchRequest(query=payload.question, top_k=payload.top_k),
    )
    context_payload = DefaultContextBuilder().build(
        BuildContextRequest(
            hits=[
                RetrievalHit(
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    score=item.score,
                    text=item.text,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    heading_path=item.heading_path,
                    route=item.route,
                )
                for item in search_response.items
            ],
            document_titles={item.document_id: item.document_title for item in search_response.items},
            max_characters=settings.context_builder_max_characters,
            max_blocks=settings.context_builder_max_blocks,
        )
    )
    return AnswerVerifier().verify(answer_text=payload.answer_text, context_payload=context_payload)
