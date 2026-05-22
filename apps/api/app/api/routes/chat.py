from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.answer_verifier import AnswerVerifier
from app.services.chat_service import ChatService
from app.services.citation_resolver import CitationResolver
from app.services.context_builder import DefaultContextBuilder
from app.services.retrieval.search_service import SearchService

router = APIRouter()


def _build_chat_service(request: Request) -> ChatService:
    retriever = getattr(request.app.state, "search_retriever", None)
    if retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search retrieval is not configured yet. Configure a search retriever before using /chat.",
        )

    settings = request.app.state.settings
    if settings.llm_backend == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM generation is not configured yet. Configure an LLM backend before using /chat.",
        )

    llm_backend = getattr(request.app.state, "llm_backend", None)
    if llm_backend is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM generation is not configured yet. Configure an LLM backend before using /chat.",
        )

    return ChatService(
        search_service=SearchService(retriever=retriever),
        context_builder=DefaultContextBuilder(),
        llm_backend=llm_backend,
        citation_resolver=CitationResolver(),
        answer_verifier=AnswerVerifier(),
        max_context_characters=settings.context_builder_max_characters,
        max_context_blocks=settings.context_builder_max_blocks,
    )


@router.post("", response_model=ChatResponse)
def chat_route(
    request: Request,
    payload: ChatRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> ChatResponse:
    return _build_chat_service(request).answer(context=context, payload=payload, delivery_mode="blocking")


@router.post("/stream")
def chat_stream_route(
    request: Request,
    payload: ChatRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> StreamingResponse:
    result = _build_chat_service(request).answer(context=context, payload=payload, delivery_mode="streaming")

    def _events():
        yield "event: start\ndata: {}\n\n"
        yield f"event: answer\ndata: {json.dumps(result.model_dump(), separators=(",", ":"))}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
